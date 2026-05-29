"""
Modulo AWS Lambda per la generazione dinamica di projects.json, home_projects.json, layouts.json, adpe.json e contatti.json.
Include l'applicazione automatica dell'header Cache-Control per le immagini.
"""

import os
import json
import boto3
import requests
import base64
import io
from urllib.parse import quote
from typing import Dict, List, Tuple, Any

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except Exception:
    Image = None
    ImageOps = None
    UnidentifiedImageError = Exception

s3_client = boto3.client("s3")

S3_BUCKET_NAME: str = os.environ.get("S3_BUCKET_NAME", "")
S3_REGION: str = os.environ.get("S3_REGION", "")
GITHUB_REPO_OWNER: str = os.environ.get("GITHUB_REPO_OWNER", "")
GITHUB_REPO_NAME: str = os.environ.get("GITHUB_REPO_NAME", "")
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
DERIVATIVES_BUCKET_NAME: str = os.environ.get("DERIVATIVES_BUCKET_NAME", "")
DERIVATIVES_REGION: str = os.environ.get("DERIVATIVES_REGION", S3_REGION)
DERIVATIVES_PREFIX: str = os.environ.get("DERIVATIVES_PREFIX", "_generated").strip("/")
ENABLE_IMAGE_DERIVATIVES: bool = os.environ.get("ENABLE_IMAGE_DERIVATIVES", "true").lower() in ("1", "true", "yes", "on")

IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.jfif')
DERIVATIVE_WIDTHS = {
    "thumb": 720,
    "medium": 1200,
    "large": 1800,
}

GITHUB_HEADERS: Dict[str, str] = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

# =====================================================================
# FUNZIONE PER IL CACHING DELLE IMMAGINI
# =====================================================================
def apply_cache_control(bucket_name: str, object_key: str) -> None:
    """
    Controlla se il file è un'immagine e, se non ce l'ha,
    applica l'header Cache-Control (1 anno, senza immutable).
    """
    if not object_key.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.jfif')):
        return
        
    try:
        response = s3_client.head_object(Bucket=bucket_name, Key=object_key)
        content_type = response.get('ContentType', 'image/jpeg')
        current_cache = response.get('CacheControl', '')
        
        # Rimosso 'immutable' poiché i file potrebbero essere sovrascritti con lo stesso nome
        target_cache = 'public, max-age=31536000'
        
        if current_cache == target_cache:
            return

        print(f"Aggiorno Cache-Control per {object_key}...")
        
        s3_client.copy_object(
            Bucket=bucket_name,
            Key=object_key,
            CopySource={'Bucket': bucket_name, 'Key': object_key},
            MetadataDirective='REPLACE',
            ContentType=content_type,
            CacheControl=target_cache
        )
        print(f"Cache-Control applicato con successo a {object_key}")
        
    except Exception as e:
        print(f"Errore durante l'aggiornamento della cache per {object_key}: {str(e)}")

def build_s3_url(bucket_name: str, region: str, object_key: str) -> str:
    """Costruisce un URL S3 pubblico con key correttamente URL-encoded."""
    encoded_key = quote(object_key, safe="/")
    return f"https://{bucket_name}.s3.{region}.amazonaws.com/{encoded_key}"

def derivative_key_for(source_key: str, etag: str, width: int) -> str:
    """
    Genera una chiave versionata per la derivata.
    L'ETag nel nome evita cache stale quando un file viene sovrascritto con lo stesso nome.
    """
    base, _ = os.path.splitext(source_key)
    safe_etag = (etag or "noetag").replace('"', '').replace("-", "")
    return f"{DERIVATIVES_PREFIX}/{base}.{safe_etag}.w{width}.webp"

def derivatives_enabled_for(object_key: str) -> bool:
    if not ENABLE_IMAGE_DERIVATIVES or not DERIVATIVES_BUCKET_NAME or not Image:
        return False
    lower_key = object_key.lower()
    if not lower_key.endswith(IMAGE_EXTENSIONS):
        return False
    # Evita di rompere GIF animate: restano servite come originali.
    if lower_key.endswith(".gif"):
        return False
    return True

def object_exists(bucket_name: str, object_key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket_name, Key=object_key)
        return True
    except Exception:
        return False

def normalize_image_mode(image: Any) -> Any:
    if image.mode in ("RGB", "RGBA"):
        return image
    if image.mode in ("P", "LA") or ("transparency" in image.info):
        return image.convert("RGBA")
    return image.convert("RGB")

def generate_image_derivatives(bucket_name: str, object_key: str, source_obj: Dict[str, Any]) -> Dict[str, str]:
    """
    Crea versioni WebP leggere in un bucket tecnico separato.
    Ritorna URL pubblici da inserire nel JSON, mantenendo sempre src originale come fallback.
    """
    if not derivatives_enabled_for(object_key):
        return {}

    etag = str(source_obj.get("ETag", "")).strip('"')
    expected = {
        label: derivative_key_for(object_key, etag, width)
        for label, width in DERIVATIVE_WIDTHS.items()
    }

    result: Dict[str, str] = {
        label: build_s3_url(DERIVATIVES_BUCKET_NAME, DERIVATIVES_REGION, key)
        for label, key in expected.items()
        if object_exists(DERIVATIVES_BUCKET_NAME, key)
    }

    missing = {label: key for label, key in expected.items() if label not in result}
    if not missing:
        return result

    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        raw_bytes = response["Body"].read()

        with Image.open(io.BytesIO(raw_bytes)) as original:
            if getattr(original, "is_animated", False):
                return {}

            image = ImageOps.exif_transpose(original)
            image = normalize_image_mode(image)

            for label, derivative_key in missing.items():
                width = DERIVATIVE_WIDTHS[label]
                out_image = image

                if image.width > width:
                    ratio = width / float(image.width)
                    height = max(1, int(image.height * ratio))
                    out_image = image.resize((width, height), Image.Resampling.LANCZOS)

                buffer = io.BytesIO()
                out_image.save(buffer, format="WEBP", quality=80, method=6)
                buffer.seek(0)

                s3_client.put_object(
                    Bucket=DERIVATIVES_BUCKET_NAME,
                    Key=derivative_key,
                    Body=buffer.getvalue(),
                    ContentType="image/webp",
                    CacheControl="public, max-age=31536000, immutable",
                )
                result[label] = build_s3_url(DERIVATIVES_BUCKET_NAME, DERIVATIVES_REGION, derivative_key)

    except UnidentifiedImageError:
        print(f"Immagine non riconosciuta, salto derivati: {object_key}")
    except Exception as e:
        print(f"Errore durante la generazione derivati per {object_key}: {str(e)}")

    return result

# =====================================================================
# FUNZIONI DI GITHUB E PARSING
# =====================================================================
def get_s3_object_content(key: str) -> str:
    """Scarica e restituisce il contenuto di un oggetto S3 come stringa."""
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        return response["Body"].read().decode("utf-8")
    except Exception as e:
        return ""

def push_to_github(file_path: str, json_data: Any, message: str) -> None:
    """Aggiorna un file su GitHub solo se il contenuto è effettivamente cambiato."""
    url = f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{file_path}"
    
    sha = None
    current_content = None
    
    resp = requests.get(url, headers=GITHUB_HEADERS)
    if resp.status_code == 200:
        file_data = resp.json()
        sha = file_data.get("sha")
        current_content = base64.b64decode(file_data.get("content", "")).decode("utf-8")

    new_content_str = json.dumps(json_data, indent=2, ensure_ascii=False)

    if current_content == new_content_str:
        print(f"Nessuna modifica per {file_path}, skip commit.")
        return

    payload = {
        "message": message,
        "content": base64.b64encode(new_content_str.encode("utf-8")).decode("utf-8"),
        "branch": "master" 
    }
    if sha:
        payload["sha"] = sha

    put_resp = requests.put(url, headers=GITHUB_HEADERS, json=payload)
    put_resp.raise_for_status()
    print(f"{file_path} aggiornato con successo su GitHub!")

def parse_home_projects(content: str) -> List[str]:
    if not content:
        return []
    raw_items = content.replace('\n', ',').split(',')
    return [item.strip() for item in raw_items if item.strip()]

def parse_layouts(content: str) -> Dict[str, Any]:
    if not content:
        return {}
    layouts: Dict[str, Any] = {}
    current_layout = None
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('[') and line.endswith(']'):
            current_layout = line[1:-1].strip()
            layouts[current_layout] = {"slots": []}
        elif current_layout and '=' in line:
            key, val = [x.strip() for x in line.split('=', 1)]
            key_lower = key.lower()
            if key_lower == 'slot':
                parts = [p.strip() for p in val.split(',')]
                slot_dict = {"col": parts[0]}
                if len(parts) > 1:
                    slot_dict["row"] = parts[1]
                layouts[current_layout]["slots"].append(slot_dict)
            elif key_lower in ['columns', 'rows']:
                layouts[current_layout][key_lower] = int(val) if val.isdigit() else val
            else:
                layouts[current_layout][key_lower] = val
    return layouts

def parse_project_description(content: str) -> str:
    return content.strip() if content else ""

def format_folder_name_to_title(name: str) -> str:
    return " ".join(word.capitalize() for word in name.replace("-", " ").split())

def list_folders(prefix: str) -> List[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix, Delimiter="/")
    folders: List[str] = []
    for page in pages:
        if "CommonPrefixes" in page:
            for cp in page["CommonPrefixes"]:
                folders.append(cp["Prefix"])
    return folders

# =====================================================================
# LOGICA PROGETTI
# =====================================================================
def has_files(prefix: str) -> bool:
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix, Delimiter="/")
    for page in pages:
        if "Contents" in page:
            for obj in page["Contents"]:
                file_name = os.path.basename(obj["Key"]).lower()
                if file_name == "description.txt" or file_name.endswith((".jpg", ".jpeg", ".png", ".gif", ".jfif", ".webp")):
                    return True
    return False

def build_json(prefix: str, project_id: int) -> Tuple[Dict[str, Any], int]:
    data: Dict[str, Any] = {}
    for folder in sorted(list_folders(prefix)):
        name = os.path.basename(folder.strip("/"))
        if has_files(folder):
            project = process_project(folder, project_id)
            data[name] = project
            project_id += 1
        else:
            sub_json, project_id = build_json(folder, project_id)
            data[name] = sub_json
    return data, project_id

def process_project(prefix: str, project_id: int) -> Dict[str, Any]:
    folder_name: str = os.path.basename(prefix.strip("/"))
    title: str = format_folder_name_to_title(folder_name)
    
    metadata: Dict[str, Any] = {
        "description": "", "luogo_data": "", "posizione": "", 
        "stato": "", "committente": "", "tipologia": "", "layoutSequence": []
    }
    images: List[Tuple[str, str, Dict[str, str]]] = []
    image_desc: Dict[str, str] = {}

    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix)

    for page in pages:
        if "Contents" not in page: continue
        for obj in page["Contents"]:
            key = obj["Key"]
            file_name = os.path.basename(key)
            file_name_lower = file_name.lower()
            if key == prefix or not file_name: continue
            
            if file_name_lower == "description.txt": metadata["description"] = parse_project_description(get_s3_object_content(key))
            elif file_name_lower == "luogo_data.txt": metadata["luogo_data"] = parse_project_description(get_s3_object_content(key))
            elif file_name_lower == "posizione.txt": metadata["posizione"] = parse_project_description(get_s3_object_content(key))
            elif file_name_lower == "stato.txt": metadata["stato"] = parse_project_description(get_s3_object_content(key))
            elif file_name_lower == "committente.txt": metadata["committente"] = parse_project_description(get_s3_object_content(key))
            elif file_name_lower == "tipologia.txt": metadata["tipologia"] = parse_project_description(get_s3_object_content(key))
            elif file_name_lower == "layoutsequence.txt":
                content = parse_project_description(get_s3_object_content(key))
                if content: metadata["layoutSequence"] = [item.strip() for item in content.replace('\n', ',').split(',') if item.strip()]
            elif file_name_lower.endswith(IMAGE_EXTENSIONS):
                url = f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{key}"
                variants = generate_image_derivatives(S3_BUCKET_NAME, key, obj)
                images.append((file_name, url, variants))
                
                # --- [NUOVO] Applica il caching all'immagine trovata nei progetti ---
                apply_cache_control(S3_BUCKET_NAME, key)

            elif file_name_lower.endswith(".txt"):
                base_name = os.path.splitext(file_name_lower)[0]
                content = get_s3_object_content(key)
                if content: image_desc[base_name] = content.strip()

    images.sort(key=lambda x: x[0].lower())
    final_images: List[Dict[str, str]] = []
    for img_name, url, variants in images:
        image_obj = {
            "src": url,
            "description": image_desc.get(os.path.splitext(img_name)[0].lower(), "")
        }
        image_obj.update(variants)
        final_images.append(image_obj)

    project_data: Dict[str, Any] = {"id": project_id, "title": title}
    for k, v in metadata.items():
        if v: project_data[k] = v
    project_data["images"] = final_images
    return project_data

# =====================================================================
# LOGICA ADPE
# =====================================================================
def build_adpe_json(prefix: str = "adpe/") -> Dict[str, Any]:
    sections = []
    folders = sorted(list_folders(prefix))
    
    for folder in folders:
        folder_name = os.path.basename(folder.strip("/"))
        section_id = folder_name.split("-", 1)[-1] if "-" in folder_name else folder_name
        
        section_data = {
            "id": section_id,
            "title": get_s3_object_content(f"{folder}title.txt").strip(),
            "subtitle": get_s3_object_content(f"{folder}subtitle.txt").strip(),
            "layout": get_s3_object_content(f"{folder}layout.txt").strip() or "PROJECT_SINGLE",
            "text": get_s3_object_content(f"{folder}text.txt").strip(),
            "images": []
        }
        
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=folder)
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    if key.lower().endswith(IMAGE_EXTENSIONS):
                        url = f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{key}"
                        img_obj = {"src": url, "description": ""}
                        img_obj.update(generate_image_derivatives(S3_BUCKET_NAME, key, obj))
                        section_data["images"].append(img_obj)
                        
                        # --- [NUOVO] Applica il caching all'immagine trovata in ADPE ---
                        apply_cache_control(S3_BUCKET_NAME, key)
                        break 
                        
        sections.append(section_data)
        
    return {"sections": sections}

# =====================================================================
# LOGICA CONTATTI
# =====================================================================
def build_contatti_json(prefix: str = "contatti/") -> Dict[str, Any]:
    sections = []
    
    # 1. Scansiona le sotto-cartelle dinamiche (es: 01-lo-studio/, 02-mappa/)
    folders = sorted(list_folders(prefix))
    for folder in folders:
        folder_name = os.path.basename(folder.strip("/"))
        section_id = folder_name.split("-", 1)[-1] if "-" in folder_name else folder_name
        
        section_data = {
            "id": section_id,
            "title": get_s3_object_content(f"{folder}title.txt").strip(),
            "subtitle": get_s3_object_content(f"{folder}subtitle.txt").strip(),
            "layout": get_s3_object_content(f"{folder}layout.txt").strip() or "PROJECT_SINGLE_VERTICAL",
            "text": get_s3_object_content(f"{folder}text.txt").strip(),
            "images": []
        }

        # Legge il link opzionale (es. Google Maps) condiviso per le immagini di questa cartella
        custom_link = get_s3_object_content(f"{folder}link.txt").strip()

        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=folder)
        
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    if key.lower().endswith(IMAGE_EXTENSIONS):
                        url = f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{key}"
                        
                        img_obj = {"src": url, "description": ""}
                        img_obj.update(generate_image_derivatives(S3_BUCKET_NAME, key, obj))
                        if custom_link:
                            img_obj["link"] = custom_link
                            
                        # [CORRETTO]: Append inserito dentro l'IF dell'estensione immagine
                        section_data["images"].append(img_obj)
                        
                        # --- Applica il caching all'immagine trovata in Contatti ---
                        apply_cache_control(S3_BUCKET_NAME, key)
                        
        # Ordina le immagini alfabeticamente per nome file all'interno della sezione (opzionale ma consigliato)
        section_data["images"].sort(key=lambda x: x["src"].lower())
        
        # Aggiunge la sezione all'array globale solo se contiene effettivamente dati o immagini
        sections.append(section_data)
        
    # 2. Compila i dati globali statici in fondo (Telefono, Email, Social)
    data = {
        "sections": sections,
        "phone": {
            "label": get_s3_object_content(f"{prefix}phone_label.txt").strip() or "Telefono",
            "text": get_s3_object_content(f"{prefix}phone_text.txt").strip()
        },
        "email": {
            "label": get_s3_object_content(f"{prefix}email_label.txt").strip() or "Email",
            "text": get_s3_object_content(f"{prefix}email_text.txt").strip()
        },
        "social": {
            # Se la label social è vuota non inserisce una chiave inutile, mappa i link diretti
            "instagram": get_s3_object_content(f"{prefix}instagram.txt").strip(),
            "facebook": get_s3_object_content(f"{prefix}facebook.txt").strip(),
            "linkedin": get_s3_object_content(f"{prefix}linkedin.txt").strip()
        }
    }
    
    # Rimuove l'etichetta social dal payload se non ci sono account associati per pulizia
    if data["social"] and get_s3_object_content(f"{prefix}social_label.txt").strip():
        data["social"]["label"] = get_s3_object_content(f"{prefix}social_label.txt").strip()
        
    return data

# =====================================================================
# LOGICA TEMA (THEME)
# =====================================================================
def build_theme_json(prefix: str = "theme/") -> Dict[str, str]:
    data = {
        "backgroundColor": get_s3_object_content(f"{prefix}background_color.txt").strip(),
        "hoverColor": get_s3_object_content(f"{prefix}hover_color.txt").strip(),
        "fontFamily": get_s3_object_content(f"{prefix}font_family.txt").strip(),
        "fontUrl": get_s3_object_content(f"{prefix}font_url.txt").strip()
    }
    # Filtra le chiavi vuote (se un file .txt non esiste, non lo mette nel JSON)
    return {k: v for k, v in data.items() if v}

# =====================================================================
# HANDLER PRINCIPALE
# =====================================================================

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        # --- [NUOVO] Gestione delle immagini statiche ---
        # Se ci sono immagini libere nel bucket (come adpelogo.jpg) che non
        # vengono lette dai metodi build_json, assicuriamoci di processarle.
        static_prefix = "static/"
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=static_prefix)
        for page in pages:
            if "Contents" in page:
                for obj in page["Contents"]:
                    apply_cache_control(S3_BUCKET_NAME, obj["Key"])


        # 1. ELABORAZIONE projects.json
        projects_data, _ = build_json("projects/", 1)
        push_to_github("projects.json", projects_data, "Aggiornamento projects.json da S3")

        # 2. ELABORAZIONE home_projects.json
        home_txt_content = get_s3_object_content("selezione_home_projects.txt")
        if home_txt_content:
            home_data = parse_home_projects(home_txt_content)
            push_to_github("home_projects.json", home_data, "Aggiornamento vetrina da S3")

        # 3. ELABORAZIONE layouts.json
        layouts_txt_content = get_s3_object_content("layouts.txt")
        if layouts_txt_content:
            layouts_data = parse_layouts(layouts_txt_content)
            push_to_github("layouts.json", layouts_data, "Aggiornamento layouts da S3")

        # 4. ELABORAZIONE adpe.json
        adpe_data = build_adpe_json("adpe/")
        push_to_github("adpe.json", adpe_data, "Aggiornamento adpe.json da S3")

        # 5. ELABORAZIONE contatti.json
        contatti_data = build_contatti_json("contatti/")
        push_to_github("contatti.json", contatti_data, "Aggiornamento contatti.json da S3")

        # 6. ELABORAZIONE ordine_progetti.json
        ordine_globale_content = get_s3_object_content("ordine_progetti.txt")
        if ordine_globale_content:
            ordine_globale_data = parse_home_projects(ordine_globale_content) 
            push_to_github("ordine_progetti.json", ordine_globale_data, "Aggiornamento ordine globale progetti da S3")
        else:
            push_to_github("ordine_progetti.json", [], "Reset ordine globale progetti")
        
        # 7. ELABORAZIONE theme.json
        theme_data = build_theme_json("theme/")
        if theme_data:
            push_to_github("theme.json", theme_data, "Aggiornamento theme.json da S3")
        else:
            push_to_github("theme.json", {}, "Reset theme.json")

        return {
            "statusCode": 200,
            "body": json.dumps("Sincronizzazione completa S3 -> GitHub effettuata con successo!"),
        }

    except Exception as e:
        print(f"ERRORE CRITICO: {e}")
        return {"statusCode": 500, "body": json.dumps(str(e))}

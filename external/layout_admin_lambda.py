"""
Lambda REST amministrativa per ADPE Admin.

Espone piccole API per leggere progetti/layout dal bucket editoriale e scrivere:
- layouts.txt
- projects/.../layoutsequence.txt
- avviare la build hook Netlify di produzione

La Lambda principale S3 -> GitHub resta invariata: quando questa funzione scrive
su S3, il trigger esistente aggiorna JSON, GitHub e Netlify.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
from urllib.request import Request, urlopen

import boto3

s3_client = boto3.client("s3")

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "")
S3_REGION = os.environ.get("S3_REGION", "eu-north-1")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
NETLIFY_BUILD_HOOK_URL = os.environ.get("NETLIFY_BUILD_HOOK_URL", "")

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".jfif", ".webp")


def response(status_code: int, body: Any = None) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Access-Control-Allow-Headers": "content-type,authorization",
            "Access-Control-Allow-Methods": "GET,PUT,POST,OPTIONS",
            "Content-Type": "application/json; charset=utf-8",
        },
        "body": json.dumps(body if body is not None else {}, ensure_ascii=False),
    }


def authorize(event: Dict[str, Any]) -> bool:
    if not ADMIN_TOKEN:
        return True
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    return auth == f"Bearer {ADMIN_TOKEN}"


def read_s3_text(key: str) -> str:
    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        return obj["Body"].read().decode("utf-8")
    except Exception:
        return ""


def write_s3_text(key: str, content: str) -> None:
    s3_client.put_object(
        Bucket=S3_BUCKET_NAME,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/plain; charset=utf-8",
    )


def s3_url(key: str) -> str:
    return f"https://{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com/{quote(key, safe='/')}"


def basename_from_prefix(prefix: str) -> str:
    return os.path.basename(prefix.strip("/"))


def title_from_folder(folder_name: str) -> str:
    return " ".join(part.capitalize() for part in folder_name.replace("-", " ").replace("_", " ").split())


def list_folders(prefix: str) -> List[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix, Delimiter="/")
    folders: List[str] = []
    for page in pages:
        for cp in page.get("CommonPrefixes", []):
            folders.append(cp["Prefix"])
    return sorted(folders)


def list_project_images(prefix: str) -> List[Dict[str, str]]:
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix)
    images: List[Tuple[str, str]] = []
    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            file_name = os.path.basename(key)
            if not file_name:
                continue
            if file_name.lower().endswith(IMAGE_EXTENSIONS):
                images.append((file_name.lower(), key))
    images.sort(key=lambda item: item[0])
    return [{"key": key, "src": s3_url(key), "name": os.path.basename(key)} for _, key in images]


def project_has_direct_content(prefix: str) -> bool:
    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix, Delimiter="/")
    for page in pages:
        for obj in page.get("Contents", []):
            file_name = os.path.basename(obj["Key"]).lower()
            if file_name == "description.txt" or file_name.endswith(IMAGE_EXTENSIONS):
                return True
    return False


def collect_projects(prefix: str = "projects/") -> List[Dict[str, str]]:
    projects: List[Dict[str, str]] = []

    def walk(folder: str, path_parts: List[str]) -> None:
        for child in list_folders(folder):
            name = basename_from_prefix(child)
            next_parts = [*path_parts, name]
            if project_has_direct_content(child):
                projects.append({
                    "path": child,
                    "name": name,
                    "title": title_from_folder(name),
                    "categoryPath": ".".join(next_parts),
                })
            walk(child, next_parts)

    walk(prefix, [])
    return projects


def parse_layouts(content: str) -> Dict[str, Any]:
    layouts: Dict[str, Any] = {}
    current: Optional[str] = None
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            layouts[current] = {"slots": []}
            continue
        if not current or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        key_l = key.lower()
        if key_l == "slot":
            parts = [part.strip() for part in value.split(",")]
            slot = {"col": parts[0]}
            if len(parts) > 1:
                slot["row"] = parts[1]
            layouts[current]["slots"].append(slot)
        elif key_l in ("columns", "rows"):
            layouts[current][key_l] = int(value) if value.isdigit() else value
        else:
            layouts[current][key_l] = value
    return layouts


def split_layout_blocks(content: str) -> List[Tuple[Optional[str], str]]:
    blocks: List[Tuple[Optional[str], str]] = []
    current_name: Optional[str] = None
    current_lines: List[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if current_lines:
                blocks.append((current_name, "\n".join(current_lines).strip()))
            current_name = stripped[1:-1].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append((current_name, "\n".join(current_lines).strip()))
    return blocks


def upsert_layout_block(content: str, layout_name: str, layout_text: str) -> str:
    clean_name = layout_name.strip()
    clean_block = layout_text.strip()
    if not clean_block.startswith(f"[{clean_name}]"):
        clean_block = f"[{clean_name}]\n{clean_block}"

    blocks = split_layout_blocks(content)
    updated: List[str] = []
    replaced = False
    for name, block in blocks:
        if name == clean_name:
            updated.append(clean_block)
            replaced = True
        elif block:
            updated.append(block)

    if not replaced:
        updated.append(clean_block)

    return "\n\n".join(updated).strip() + "\n"


def parse_json_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def get_query(event: Dict[str, Any]) -> Dict[str, str]:
    return event.get("queryStringParameters") or {}


def handle_get_projects() -> Dict[str, Any]:
    return response(200, {"projects": collect_projects()})


def handle_get_layouts() -> Dict[str, Any]:
    raw = read_s3_text("layouts.txt")
    return response(200, {"raw": raw, "layouts": parse_layouts(raw)})


def handle_get_project(event: Dict[str, Any]) -> Dict[str, Any]:
    project_path = get_query(event).get("path", "")
    if not project_path.startswith("projects/") or not project_path.endswith("/"):
        return response(400, {"error": "Invalid project path"})

    layout_sequence = [
        item.strip()
        for item in read_s3_text(f"{project_path}layoutsequence.txt").replace(",", "\n").splitlines()
        if item.strip()
    ]
    return response(200, {
        "path": project_path,
        "name": basename_from_prefix(project_path),
        "title": title_from_folder(basename_from_prefix(project_path)),
        "images": list_project_images(project_path),
        "layoutSequence": layout_sequence,
    })


def handle_put_layout(event: Dict[str, Any]) -> Dict[str, Any]:
    data = parse_json_body(event)
    layout_name = str(data.get("name", "")).strip()
    layout_text = str(data.get("layoutText", "")).strip()
    if not layout_name or not layout_text:
        return response(400, {"error": "Missing name or layoutText"})

    raw = read_s3_text("layouts.txt")
    updated = upsert_layout_block(raw, layout_name, layout_text)
    write_s3_text("layouts.txt", updated)
    return response(200, {"ok": True, "name": layout_name})


def handle_put_project_sequence(event: Dict[str, Any]) -> Dict[str, Any]:
    data = parse_json_body(event)
    project_path = str(data.get("projectPath", ""))
    sequence = data.get("sequence", [])
    if not project_path.startswith("projects/") or not project_path.endswith("/"):
        return response(400, {"error": "Invalid project path"})
    if not isinstance(sequence, list) or not all(str(item).strip() for item in sequence):
        return response(400, {"error": "Invalid sequence"})

    content = "\n".join(str(item).strip() for item in sequence) + "\n"
    write_s3_text(f"{project_path}layoutsequence.txt", content)
    return response(200, {"ok": True, "projectPath": project_path, "sequence": sequence})


def handle_save(event: Dict[str, Any]) -> Dict[str, Any]:
    data = parse_json_body(event)
    layout_name = str(data.get("name", "")).strip()
    layout_text = str(data.get("layoutText", "")).strip()
    project_path = str(data.get("projectPath", ""))
    sequence = data.get("sequence", [])

    if layout_name and layout_text:
        raw = read_s3_text("layouts.txt")
        write_s3_text("layouts.txt", upsert_layout_block(raw, layout_name, layout_text))

    if project_path and sequence:
        if not project_path.startswith("projects/") or not project_path.endswith("/"):
            return response(400, {"error": "Invalid project path"})
        content = "\n".join(str(item).strip() for item in sequence if str(item).strip()) + "\n"
        write_s3_text(f"{project_path}layoutsequence.txt", content)

    return response(200, {"ok": True})


def handle_publish() -> Dict[str, Any]:
    if not NETLIFY_BUILD_HOOK_URL:
        return response(400, {"error": "Missing NETLIFY_BUILD_HOOK_URL"})

    req = Request(NETLIFY_BUILD_HOOK_URL, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=20) as res:
        status = getattr(res, "status", 200)
        if status < 200 or status >= 300:
            return response(502, {"error": f"Netlify hook returned HTTP {status}"})
    return response(200, {"ok": True})


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("requestContext", {}).get("http"):
        method = event["requestContext"]["http"]["method"]
        path = event.get("rawPath", "/")
    else:
        method = event.get("httpMethod", "GET")
        path = event.get("path", "/")

    if method == "OPTIONS":
        return response(200, {})

    if not authorize(event):
        return response(401, {"error": "Unauthorized"})

    try:
        if method == "GET" and path.endswith("/projects"):
            return handle_get_projects()
        if method == "GET" and path.endswith("/project"):
            return handle_get_project(event)
        if method == "GET" and path.endswith("/layouts"):
            return handle_get_layouts()
        if method == "PUT" and path.endswith("/layout"):
            return handle_put_layout(event)
        if method == "PUT" and path.endswith("/project-layout-sequence"):
            return handle_put_project_sequence(event)
        if method in ("PUT", "POST") and path.endswith("/save"):
            return handle_save(event)
        if method == "POST" and path.endswith("/publish"):
            return handle_publish()
        return response(404, {"error": "Not found", "path": path, "method": method})
    except Exception as exc:
        print(f"Layout admin error: {exc}")
        return response(500, {"error": str(exc)})

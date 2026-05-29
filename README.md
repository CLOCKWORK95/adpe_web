# ADPE Web

Sito web vetrina per ADPE Studio di Architettura.

Il progetto e' un sito statico pubblicato su Netlify, alimentato da file JSON
generati automaticamente a partire da una struttura di cartelle su AWS S3. Gli
architetti possono aggiornare progetti, immagini, testi, layout e alcune
impostazioni grafiche direttamente da un client S3 come S3 Browser o Cyberduck,
senza modificare codice.

## Sommario

- [Come funziona](#come-funziona)
- [Ruoli e responsabilita](#ruoli-e-responsabilita)
- [Struttura della repository](#struttura-della-repository)
- [Struttura del bucket S3](#struttura-del-bucket-s3)
- [Gestione dei progetti da S3](#gestione-dei-progetti-da-s3)
- [Gestione della home](#gestione-della-home)
- [Gestione dei layout](#gestione-dei-layout)
- [Gestione pagine ADPE e Contatti](#gestione-pagine-adpe-e-contatti)
- [Gestione tema grafico](#gestione-tema-grafico)
- [Pipeline tecnica S3 -> GitHub -> Netlify](#pipeline-tecnica-s3---github---netlify)
- [Deploy e ambienti](#deploy-e-ambienti)
- [Regole operative per gli architetti](#regole-operative-per-gli-architetti)
- [Manutenzione tecnica](#manutenzione-tecnica)
- [Troubleshooting](#troubleshooting)

## Come funziona

La sorgente editoriale del sito e' il bucket S3. La repository GitHub contiene
il codice statico del sito e i JSON derivati dai contenuti presenti nel bucket.

Flusso generale:

1. Un architetto modifica cartelle, immagini o file `.txt` nel bucket S3.
2. Una AWS Lambda viene triggerata dalla modifica del bucket.
3. La Lambda legge la struttura S3 e rigenera i JSON del sito.
4. La Lambda aggiorna i file JSON nella repository GitHub.
5. Netlify riceve le modifiche da GitHub e pubblica il sito statico.
6. Il browser carica `index.html` e i JSON, poi costruisce dinamicamente home,
   progetti, pagina ADPE e contatti.

Il sito non usa un CMS tradizionale come WordPress. Il "CMS" e' la struttura S3:
cartelle, immagini e piccoli file testuali.

## Ruoli e responsabilita

### Architetti / editor contenuti

Usano un client S3 per:

- aggiungere o rimuovere progetti;
- caricare immagini;
- ordinare le immagini tramite nome file;
- modificare descrizioni e metadati dei progetti;
- scegliere i progetti in home;
- cambiare la sequenza dei layout;
- aggiornare contenuti ADPE e Contatti;
- modificare colori/font tramite file testuali.

Non devono modificare `index.html`, i JSON nella repository o il codice Lambda.

### Tecnici / manutentori

Gestiscono:

- codice frontend in `index.html`;
- configurazione Netlify;
- AWS Lambda;
- permessi S3;
- token GitHub;
- validazione dei JSON;
- eventuali ottimizzazioni performance, sicurezza e SEO;
- documentazione delle regole operative.

## Struttura della repository

File principali:

```text
.
|-- index.html              # Sito statico completo: HTML, CSS e JavaScript
|-- projects.json           # Progetti generati da S3
|-- layouts.json            # Layout disponibili per home e dettaglio progetti
|-- home_projects.json      # Lista progetti selezionati per la vetrina/home
|-- ordine_progetti.json    # Ordine globale dei progetti
|-- splashpage.json         # Blocchi visuali della home splash
|-- adpe.json               # Contenuti dinamici pagina ADPE
|-- contatti.json           # Contenuti dinamici pagina Contatti
|-- theme.json              # Tema grafico dinamico
|-- netlify.toml            # Configurazione Netlify
|-- manual_deployment.html  # Pannello manuale locale/non versionato
`-- external/
    `-- lambda.py           # Codice Lambda di sincronizzazione S3 -> GitHub
```

Nota: `manual_deployment.html` e' ignorato da git tramite `.gitignore`. Serve
come riferimento operativo locale per il deploy manuale della produzione.

## Struttura del bucket S3

La Lambda si aspetta alcune cartelle e alcuni file speciali nella root del
bucket.

Schema logico:

```text
bucket-root/
|-- projects/
|   |-- design/
|   |   `-- NOME-PROGETTO/
|   |-- residenziale/
|   |   `-- NOME-PROGETTO/
|   `-- uffici/
|       `-- NOME-PROGETTO/
|-- adpe/
|   |-- 01-filosofia/
|   |-- 02-curriculum/
|   `-- 03-elenco-dei-lavori/
|-- contatti/
|   |-- 01-studio/
|   |-- 02-mappa/
|   |-- phone_label.txt
|   |-- phone_text.txt
|   |-- email_label.txt
|   |-- email_text.txt
|   |-- instagram.txt
|   |-- facebook.txt
|   `-- linkedin.txt
|-- theme/
|   |-- background_color.txt
|   |-- hover_color.txt
|   |-- font_family.txt
|   `-- font_url.txt
|-- static/
|   `-- adpelogo.jpg
|-- layouts.txt
|-- selezione_home_projects.txt
`-- ordine_progetti.txt
```

Il nome esatto del bucket e la region AWS sono configurati come variabili
d'ambiente nella Lambda.

## Gestione dei progetti da S3

I progetti si trovano sotto `projects/`.

La struttura puo' avere piu' livelli. Una cartella viene considerata progetto
quando contiene almeno:

- una immagine supportata; oppure
- un file `description.txt`.

Esempio:

```text
projects/
`-- residenziale/
    `-- AVENTINO/
        |-- 01.jpg
        |-- 02.jpg
        |-- 03.jpg
        |-- description.txt
        |-- luogo_data.txt
        |-- posizione.txt
        |-- stato.txt
        |-- committente.txt
        |-- tipologia.txt
        `-- layoutsequence.txt
```

### Immagini supportate

La Lambda riconosce come immagini:

```text
.jpg, .jpeg, .png, .gif, .jfif, .webp
```

Nel codice di caching S3 e' considerato anche `.svg`, ma i progetti nel JSON
vengono generati solo dalle estensioni indicate sopra.

### Ordine immagini

Le immagini sono ordinate alfabeticamente per nome file.

Consigli:

```text
00.jpg
01.jpg
02.jpg
03.jpg
```

oppure:

```text
01_planimetria.jpg
02_interno.jpg
03_dettaglio.jpg
```

Evitare nomi casuali se si vuole controllare l'ordine di visualizzazione.

### File testuali di progetto

Ogni progetto puo' contenere questi file:

| File | Effetto sul sito |
| --- | --- |
| `description.txt` | Descrizione principale del progetto |
| `luogo_data.txt` | Luogo e data mostrati nell'intestazione |
| `posizione.txt` | Campo metadato "POSIZIONE" |
| `stato.txt` | Campo metadato "STATO" |
| `committente.txt` | Campo metadato "COMMITTENTE" |
| `tipologia.txt` | Campo metadato "TIPOLOGIA" |
| `layoutsequence.txt` | Sequenza layout usata nel dettaglio progetto |

I file vuoti vengono ignorati.

### Descrizione delle singole immagini

Per associare una descrizione a una immagine, creare un file `.txt` con lo
stesso nome base dell'immagine.

Esempio:

```text
01.jpg
01.txt
02.jpg
02.txt
```

Il contenuto di `01.txt` diventera' la descrizione della immagine `01.jpg`.

### Nome progetto e titolo

Il titolo del progetto viene ricavato dal nome cartella.

Esempi:

```text
AVENTINO           -> Aventino
CAPO-LE-CASE      -> Capo Le Case
CELLNEX-VIOLA     -> Cellnex Viola
```

Per evitare risultati poco eleganti, usare nomi cartella chiari e coerenti.

## Gestione della home

La home usa due meccanismi distinti:

1. `splashpage.json`, presente in repository.
2. `home_projects.json`, generato da S3 a partire da `selezione_home_projects.txt`.

### Selezione progetti in home

Nel bucket S3, il file:

```text
selezione_home_projects.txt
```

contiene la lista dei progetti da mostrare nella selezione home.

Formato:

```text
Q8-NA
CELLNEX-INDUSTRIA
AVENTINO
AMI
```

Sono accettati anche valori separati da virgole:

```text
Q8-NA, CELLNEX-INDUSTRIA, AVENTINO, AMI
```

Il frontend cerca i progetti per ID numerico o per nome cartella.

### Ordine globale progetti

Nel bucket S3, il file:

```text
ordine_progetti.txt
```

controlla l'ordine dei progetti quando si navigano le categorie.

Formato consigliato:

```text
Q8-NA
CELLNEX-INDUSTRIA
UNILEVER
AMI
```

I progetti non presenti in questa lista vengono ordinati alfabeticamente dopo
quelli esplicitamente ordinati.

## Gestione dei layout

I layout sono definiti su S3 nel file:

```text
layouts.txt
```

La Lambda lo converte in `layouts.json`.

Formato:

```text
[PROJECT_SINGLE_HORIZONTAL]
columns = 12
slot = 3 / span 8

[PROJECT_PAIR_VERTICAL]
columns = 12
slot = 3 / span 3
slot = 8 / span 3
```

Ogni blocco:

- inizia con `[NOME_LAYOUT]`;
- contiene `columns`;
- contiene una o piu' righe `slot`;
- puo' contenere `rows`, `height` o altri parametri usati dal frontend.

Uno slot indica la posizione CSS Grid dell'immagine:

```text
slot = colonna
slot = colonna, riga
```

Esempi:

```text
slot = 3 / span 8
slot = 1 / span 4, 1
slot = 5 / span 4, 1 / span 2
```

### Sequenza layout per progetto

Ogni progetto puo' usare un file:

```text
layoutsequence.txt
```

Esempio:

```text
PROJECT_PAIR_VERTICAL
PROJECT_SINGLE_HORIZONTAL
PROJECT_TRIPLE_VERT
```

oppure:

```text
PROJECT_PAIR_VERTICAL, PROJECT_SINGLE_HORIZONTAL, PROJECT_TRIPLE_VERT
```

Il frontend applica i layout in sequenza fino a esaurire tutte le immagini. Se
le immagini sono piu' dei layout disponibili, la sequenza viene ripetuta.

### Layout attualmente definiti

Nel progetto attuale sono presenti:

```text
A
B
C
PROJECT_SINGLE_VERTICAL
PROJECT_SINGLE_HORIZONTAL
PROJECT_PAIR_VERTICAL
PROJECT_PAIR_HORIZONTAL
PROJECT_PAIR_HOR-VERT
PROJECT_PAIR_VERT-HOR
PROJECT_TRIPLE
PROJECT_TRIPLE_VERT
```

Attenzione: nei dati attuali risultano referenziati anche
`PROJECT_PAIR_VERT_HOR` e `PROJECT_SINGLE_VERT`, ma non sono definiti in
`layouts.json`. In questi casi il frontend usa un layout di fallback.

## Gestione pagine ADPE e Contatti

### Pagina ADPE

La pagina ADPE viene generata dalla cartella S3:

```text
adpe/
```

Ogni sottocartella diventa una sezione.

Esempio:

```text
adpe/
`-- 01-filosofia/
    |-- title.txt
    |-- subtitle.txt
    |-- layout.txt
    |-- text.txt
    `-- immagine.jpg
```

File supportati:

| File | Effetto |
| --- | --- |
| `title.txt` | Titolo sezione |
| `subtitle.txt` | Sottotitolo sezione |
| `layout.txt` | Layout usato dalla sezione |
| `text.txt` | Testo descrittivo |
| immagini | Immagini della sezione |

La Lambda prende la prima immagine valida trovata nella sezione.

### Pagina Contatti

La pagina Contatti viene generata dalla cartella:

```text
contatti/
```

Ogni sottocartella diventa una sezione dinamica.

Esempio:

```text
contatti/
`-- 02-mappa/
    |-- title.txt
    |-- subtitle.txt
    |-- layout.txt
    |-- text.txt
    |-- link.txt
    `-- map.jpg
```

Se `link.txt` e' presente, le immagini della sezione diventano cliccabili e
puntano al link indicato. Questo e' utile, per esempio, per aprire Google Maps.

I dati globali dei contatti sono nella root di `contatti/`:

```text
phone_label.txt
phone_text.txt
email_label.txt
email_text.txt
instagram.txt
facebook.txt
linkedin.txt
social_label.txt
```

## Gestione tema grafico

La cartella S3:

```text
theme/
```

contiene file testuali che modificano alcune variabili grafiche del sito.

File supportati:

| File | Esempio | Effetto |
| --- | --- | --- |
| `background_color.txt` | `#ffffff` | Sfondo principale |
| `hover_color.txt` | `#2e8b57` | Colore hover/accento |
| `font_family.txt` | `'Finlandica Headline', sans-serif` | Font CSS |
| `font_url.txt` | URL Google Fonts | Foglio stile font |

Esempio:

```text
background_color.txt
#ffffff

hover_color.txt
#2e8b57

font_family.txt
'Finlandica Headline', sans-serif

font_url.txt
https://fonts.googleapis.com/css2?family=Finlandica+Headline:wght@300;400;700&display=swap
```

## Pipeline tecnica S3 -> GitHub -> Netlify

Il codice della Lambda e' in:

```text
external/lambda.py
```

Variabili d'ambiente richieste:

```text
S3_BUCKET_NAME
S3_REGION
GITHUB_REPO_OWNER
GITHUB_REPO_NAME
GITHUB_TOKEN
```

La Lambda:

1. legge i contenuti dal bucket S3;
2. rigenera i JSON;
3. confronta il contenuto nuovo con quello gia' presente su GitHub;
4. se il file e' cambiato, aggiorna il file su GitHub;
5. applica `Cache-Control` alle immagini S3 quando necessario.

File aggiornati dalla Lambda:

```text
projects.json
home_projects.json
layouts.json
adpe.json
contatti.json
ordine_progetti.json
theme.json
```

La Lambda pusha sul branch:

```text
master
```

## Deploy e ambienti

La pubblicazione avviene tramite Netlify.

La configurazione principale e' in:

```text
netlify.toml
```

Il file contiene anche la configurazione per permettere a Netlify Image CDN di
ottimizzare le immagini remote provenienti dal bucket S3:

```toml
[images]
  remote_images = ["https://adpe-architettura-galleries.s3.eu-north-1.amazonaws.com/.*"]
```

La produzione usa una regola di ignore build:

```toml
[build]
  ignore = 'test "$SITE_NAME" = "adpeprod" && test -z "$INCOMING_HOOK_TITLE"'
```

In pratica:

- il sito test puo' aggiornarsi automaticamente dai commit;
- il sito produzione viene pubblicato solo quando viene chiamato il build hook.

## Regole operative per gli architetti

### Per aggiungere un nuovo progetto

1. Aprire il bucket con S3 Browser o Cyberduck.
2. Entrare in `projects/`.
3. Scegliere la categoria corretta, per esempio `residenziale/`.
4. Creare una nuova cartella con nome chiaro, per esempio `NUOVO-PROGETTO/`.
5. Caricare le immagini con nomi ordinati: `00.jpg`, `01.jpg`, `02.jpg`.
6. Aggiungere almeno `description.txt` se serve una descrizione.
7. Aggiungere eventuali metadati: `luogo_data.txt`, `committente.txt`, ecc.
8. Aggiungere `layoutsequence.txt` se si vuole controllare il layout del
   dettaglio.
9. Attendere la sincronizzazione Lambda -> GitHub -> Netlify.

### Per modificare un progetto esistente

1. Aprire la cartella del progetto.
2. Sostituire, aggiungere o rinominare immagini.
3. Aggiornare i file `.txt`.
4. Attendere la pubblicazione.

Nota: se si sostituisce una immagine mantenendo lo stesso nome file, potrebbero
esserci cache lato browser/CDN. In caso di urgenza, meglio usare un nuovo nome
file.

### Per cambiare l'ordine delle immagini

Rinominare i file immagine. L'ordine e' alfabetico.

Esempio:

```text
01.jpg
02.jpg
03.jpg
```

### Per cambiare i progetti in home

Modificare:

```text
selezione_home_projects.txt
```

Inserire un nome progetto per riga.

### Per cambiare l'ordine globale dei progetti

Modificare:

```text
ordine_progetti.txt
```

Inserire un nome progetto per riga, nell'ordine desiderato.

### Per cambiare layout di un progetto

Modificare nella cartella progetto:

```text
layoutsequence.txt
```

Usare solo nomi layout esistenti in `layouts.txt`.

### Per cambiare testi ADPE

Modificare i file nelle sottocartelle di:

```text
adpe/
```

### Per cambiare dati contatto

Modificare i file in:

```text
contatti/
```

## Manutenzione tecnica

### Frontend

Tutta la logica frontend e' in `index.html`.

Il JavaScript:

- carica i JSON al `DOMContentLoaded`;
- applica il tema;
- appiattisce la struttura progetti;
- genera filtri e griglie;
- gestisce viste: home, progetti, dettaglio, ADPE, contatti;
- usa Netlify Image CDN per ottimizzare le immagini S3 quando il sito gira su
  `netlify.app` o `adpe.it`.

### JSON generati

I JSON generati non dovrebbero essere modificati manualmente, perche' alla
successiva esecuzione della Lambda verranno sovrascritti.

Eccezione: `splashpage.json` al momento e' un file statico in repository e non
risulta generato dalla Lambda.

### Lambda

La Lambda usa:

- `boto3` per leggere S3 e modificare metadata immagini;
- `requests` per chiamare GitHub Contents API;
- `base64` per codificare i contenuti file richiesti da GitHub.

Quando si modifica la Lambda, verificare:

- permessi IAM su S3;
- permessi del token GitHub;
- branch target (`master`);
- trigger S3;
- timeout Lambda;
- numero di oggetti nel bucket;
- rischio di esecuzioni ravvicinate su piu' eventi S3.

### Cache immagini

La Lambda applica alle immagini:

```text
Cache-Control: public, max-age=31536000
```

Non usa `immutable`, perche' i file possono essere sovrascritti con lo stesso
nome.

Buona pratica: se una immagine deve cambiare subito sul sito pubblico,
rinominarla invece di sovrascriverla.

### Sicurezza

Non committare mai:

- token GitHub;
- credenziali AWS;
- build hook Netlify privati;
- password operative;
- file locali con segreti.

Il file `manual_deployment.html` contiene logica operativa sensibile e non e'
pensato per essere pubblicato nella repository.

## Troubleshooting

### Ho caricato un progetto ma non compare

Controllare:

- la cartella e' dentro `projects/`;
- contiene almeno una immagine valida o `description.txt`;
- le immagini hanno estensione supportata;
- la Lambda e' partita;
- GitHub ha ricevuto un commit su `projects.json`;
- Netlify ha completato il deploy.

### Il progetto compare ma le immagini sono fuori ordine

Rinominare le immagini. L'ordine e' alfabetico, non cronologico.

### Un layout non viene applicato

Controllare:

- il nome nel `layoutsequence.txt`;
- il nome nel `layouts.txt`;
- maiuscole, trattini e underscore.

Esempio: `PROJECT_PAIR_VERT-HOR` e `PROJECT_PAIR_VERT_HOR` sono nomi diversi.

### Un testo non si aggiorna

Controllare:

- nome file corretto;
- encoding UTF-8;
- file non vuoto;
- commit GitHub generato dalla Lambda;
- deploy Netlify completato.

### Una immagine sostituita mostra ancora la versione vecchia

Probabile cache browser/CDN/S3.

Soluzione consigliata: caricare la nuova immagine con un nome nuovo e aggiornare
eventuali riferimenti.

### La produzione non si aggiorna

La produzione puo' essere configurata per ignorare i deploy automatici.

Controllare:

- stato build su Netlify;
- build hook produzione;
- variabile `SITE_NAME`;
- valore di `INCOMING_HOOK_TITLE`;
- pannello manuale di pubblicazione, se usato.

## Note finali

Questo progetto e' pensato per dare autonomia editoriale allo studio senza
introdurre un CMS tradizionale. La semplicita' per gli architetti dipende dal
rispetto rigoroso delle convenzioni S3: nomi cartella chiari, file `.txt`
corretti, immagini ordinate e layout esistenti.

Prima di fare modifiche tecniche importanti e' consigliabile lavorare su una
copia del bucket o su un branch separato, validare i JSON generati e solo dopo
pubblicare in produzione.

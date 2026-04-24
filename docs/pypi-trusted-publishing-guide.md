# Capacium auf PyPI mit Trusted Publishing – Setup Guide

## Ziel

Dieses Dokument beschreibt den empfohlenen Weg, **Capacium** auf **PyPI** zu veröffentlichen – mit **GitHub Actions** und **Trusted Publishing**, also **ohne langlebigen API-Token**.

Da die PyPI-Organisation noch auf Bestätigung wartet, ist dieses Dokument so aufgebaut, dass die eigentliche Einrichtung danach direkt und ohne Umwege erfolgen kann.

---

## Grundprinzip

Für Capacium sollte **Trusted Publishing** der Standardweg sein.

Das bedeutet:

- kein dauerhaft gespeicherter `PYPI_API_TOKEN`
- kein manuelles Hinterlegen von Upload-Credentials in GitHub Secrets
- Veröffentlichung über **GitHub OIDC**
- PyPI vertraut einem konkret hinterlegten GitHub-Workflow

Damit wird Publishing sicherer, sauberer und langfristig wartbarer.

---

## Voraussetzungen

Vor dem finalen Setup sollten diese Punkte erfüllt sein:

1. GitHub-Organisation oder Repository für Capacium ist final vorhanden
2. Das Python-Paket `capacium` ist releasefähig aufgebaut
3. Das Repo enthält ein korrektes `pyproject.toml`
4. GitHub Actions ist im Repo aktiviert
5. Die PyPI-Organisation ist bestätigt oder der persönliche PyPI-Account kann den Publisher anlegen

---

## Empfohlene Zielstruktur

### GitHub

Beispiel:

- Owner: `capacium`
- Repository: `capacium`
- Workflow-Datei: `.github/workflows/publish.yml`

### PyPI

Projektname:

- `capacium`

Optionales GitHub Environment:

- `pypi`

---

## Empfohlener Ablauf

## Phase 1 – Vorbereitungen im Repo

### 1. Paketstruktur sicherstellen

Empfohlene Minimalstruktur:

```text
capacium/
├── src/
│   └── capacium/
│       ├── __init__.py
│       └── cli.py
├── tests/
├── pyproject.toml
├── README.md
├── LICENSE
└── .github/
    └── workflows/
        └── publish.yml
```

### 2. `pyproject.toml` anlegen

Die Build-Konfiguration sollte modern und einfach gehalten sein.

### 3. Releasefähiges erstes Paket vorbereiten

Auch wenn es zunächst nur ein minimales Paket ist, sollte es installierbar und sauber versioniert sein.

---

## Phase 2 – PyPI Trusted Publishing vorbereiten

Sobald die PyPI-Organisation bestätigt ist oder dein persönlicher Account die Einrichtung übernehmen kann:

### 1. Prüfen, ob `capacium` auf PyPI frei ist

Das sollte vor dem Anlegen des pending publisher geprüft werden.

### 2. Pending publisher auf PyPI anlegen

Nicht in einem bestehenden Projekt, sondern im Account-/Publishing-Bereich.

Einzutragen sind:

- **PyPI project name:** `capacium`
- **Repository owner:** `capacium`
- **Repository name:** `capacium`
- **Workflow filename:** `publish.yml`
- **Environment name:** `pypi` (optional, aber empfohlen)

Wichtig:

Ein **pending publisher reserviert den Projektnamen nicht**. Deshalb sollte zwischen Eintrag und erstem Publish nicht unnötig viel Zeit liegen.

---

## Phase 3 – GitHub Actions aktivieren

### 1. Workflow-Datei anlegen

Empfohlener Name:

- `.github/workflows/publish.yml`

### 2. GitHub Environment anlegen

Empfohlenes Environment:

- `pypi`

Optional können dort später Schutzregeln definiert werden.

### 3. Release über Tags auslösen

Empfohlener Release-Trigger:

- `v0.1.0`
- `v0.1.1`
- `v1.0.0`

---

## Phase 4 – Erster Publish

Beispiel:

```bash
 git tag v0.1.0
 git push origin v0.1.0
```

Beim ersten erfolgreichen Lauf passiert Folgendes:

1. GitHub Actions baut sdist und wheel
2. PyPI prüft die OIDC-Identität des Workflows
3. Das Projekt `capacium` wird erzeugt, falls es noch nicht existiert
4. Der Upload wird veröffentlicht
5. Der pending publisher wird in einen normalen publisher überführt

---

## Empfohlene Praxis für Capacium

## 1. Kein `PYPI_API_TOKEN` als Standard

Trusted Publishing sollte der Default sein.

Nur falls in Ausnahmefällen lokal oder manuell publiziert werden muss, wäre ein API-Token relevant.

## 2. Build und Publish trennen

Der Build-Job erstellt die Artefakte.

Der Publish-Job lädt nur die bereits gebauten Artefakte hoch.

Das hält den Ablauf sauber und reduziert Fehler.

## 3. `id-token: write` nur im Publish-Job

Nicht global für den gesamten Workflow setzen.

## 4. Workflow-Dateiname stabil halten

Wenn in PyPI `publish.yml` eingetragen wurde, sollte die Datei nicht ohne gleichzeitige Aktualisierung auf PyPI umbenannt werden.

## 5. Kein reusable workflow für den eigentlichen Trusted-Publishing-Step

Der tatsächliche Publish-Job sollte in einem normalen Top-Level-Workflow liegen.

---

## Typische Stolpersteine

### 1. Name auf PyPI nicht reserviert

Der pending publisher blockiert den Projektnamen nicht.

### 2. Falscher Workflow-Dateiname

Wenn PyPI `publish.yml` erwartet und GitHub `release.yml` ausführt, schlägt Trusted Publishing fehl.

### 3. Fehlende Berechtigung

Ohne:

```yaml
permissions:
  id-token: write
```

funktioniert Trusted Publishing nicht.

### 4. Kein gebautes Artefakt

Wenn `dist/` leer ist oder der Build scheitert, kann nichts hochgeladen werden.

### 5. Kein `pyproject.toml`

Ohne saubere Paketdefinition wird der Build unnötig fehleranfällig.

---

## Empfohlene Dateiübersicht

Zu diesem Guide gehören separat:

1. `publish.yml` – GitHub Actions Workflow für PyPI
2. `test-pypi.yml` – optionaler Workflow für TestPyPI
3. `pyproject.toml` – minimale Paketdefinition für Capacium

Diese Dateien können direkt an einen Agent Developer weitergegeben werden.

---

## Konkrete Empfehlung für das weitere Vorgehen

### Sofort vorbereiten

- Repo-Struktur finalisieren
- `pyproject.toml` anlegen
- Workflow-Dateien ins Repo legen
- GitHub Environment `pypi` vorbereiten

### Sobald PyPI-Org bestätigt ist

- pending publisher anlegen
- ggf. Namen `capacium` auf PyPI noch einmal prüfen
- Tag `v0.1.0` erstellen
- ersten Publish auslösen

### Danach

- Release-Prozess dokumentieren
- optional TestPyPI ergänzen
- optional Sigstore/Attestations bewusst mitnehmen
- Trusted Publishing als Standard festschreiben

---

## Kurzfassung

**Capacium sollte auf PyPI per Trusted Publishing veröffentlicht werden.**

Dafür braucht es:

- ein sauberes Python-Paket
- einen eingetragenen PyPI Trusted Publisher
- einen GitHub Actions Workflow mit `id-token: write`
- einen ersten Tag-Release

Kein dauerhafter API-Token ist nötig.

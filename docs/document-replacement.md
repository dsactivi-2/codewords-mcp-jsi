# Dokumentersatz — vorbereitet, nicht deployed

Ein neuer Pass verweist über `ersetzt_doc_id` auf den alten abgelehnten/defekten Pass.
Der alte Datensatz und sein Verlauf bleiben unverändert. Die MCP-Übersicht verwendet
den aktuellen Nachfolger mit Status 3, nicht den höchsten historischen Statuswert.
Status 3 heißt „Hochgeladen“, nicht „von einem Menschen geprüft“.

## Speicherung und Grenzen

- `migrations/001_document_replacement.sql` ergänzt drei nullable Spalten sowie Indizes
  und die Routine `jobstep_document_intake_v1`. Sie schreibt keine bestehenden Status um.
- Der Python-Dienst ruft diese Routine einmal auf. Kandidatensperre, vollständige
  Duplikatprüfung ohne Listenlimit, Dokument, Dateieintrag und Verlauf liegen in einer
  Transaktion auf derselben Verbindung. Jeder Fehler rollt die drei Einträge zurück.
- Der Schlüssel für eine Aufnahme ergibt sich aus Kandidat, Auftrag, Typ und Vorgänger.
  Identische Aufrufe liefern dieselbe ID; eine andere Datei für denselben Vorgang
  wird abgewiesen. Ein Vorgänger darf nur einen direkten Nachfolger haben.
- Ersatz ist nur für 21/24 erlaubt. Andere aktuelle Zustände, unbekannte Alt-Typen,
  mehrere aktuelle Alt-Dokumente und falsche Zuordnung führen zum Abbruch.
- Derselbe Typ in einem anderen Auftrag oder bei einem anderen Kandidaten blockiert nicht.
- Der Vorgänger wird vor der Prüfung gesperrt. Ein SQL-Trigger verhindert danach,
  dass Status, Datei oder Zuordnung eines bereits ersetzten Dokuments überschrieben
  werden — auch über die bisherige CRM-Schreibstrecke. Das Team muss den aktuellen
  Nachfolger bearbeiten. Diese beabsichtigte Einschränkung für historische Vorgänger
  ist vor dem Roll-out mit der CRM-Oberfläche zu prüfen.
- Die Serialisierung gilt für Intake-Aufrufe dieser Routine. Unabhängige Schreibwege
  im bestehenden CRM müssen beim späteren Roll-out ebenfalls geprüft werden; sie
  erhalten durch diesen PR nicht automatisch dieselbe Kandidatensperre.
- Dies ist keine Datei-Inhaltserkennung: gleiche Bytes unter verschiedenen URLs
  werden nicht gehasht. Die Sperre verhindert doppelte logische Intake-Vorgänge.
- Die vorhandene CRM-Weboberfläche gehört zu einem anderen Projekt und wurde nicht
  geändert. Nachgewiesen wird hier die Darstellung im MCP-Soll-Ist-Abgleich.

## Voraussetzungen vor einem späteren Roll-out

Nicht beim Start migrieren. SQL-Datei zuerst von einem Administrator auf Staging
prüfen und manuell anwenden. Die vier Tabellen für Kandidatensperre und Schreibvorgänge
müssen InnoDB sein. Das produktive Schema ist gegen die verwendeten Spalten und
Indexnamen zu prüfen; die synthetische Test-Fixture ersetzt diesen Vergleich nicht.
Routine und Trigger unter strengem SQL-Modus anlegen. Der Service-Account benötigt EXECUTE und
die schon vorher verwendeten Tabellenrechte; `SQL SECURITY INVOKER` vergibt keine neuen Rechte.

DDL committet implizit. Bei teilweise fehlgeschlagener Migration nicht blind erneut
ausführen. Neue Version erst nach vollständiger Migration starten. Fehlt die Routine,
bricht Intake ab, ohne einen Datensatz anzulegen.

CodeWords/Pipedream liefert CALL-Ergebnisse möglicherweise verschachtelt zurück.
Der Parser akzeptiert flache/verschachtelte Resultsets und verlangt genau eine
markierte Antwort mit Dokument-ID. Die echte Connector-Rückgabe muss auf Staging
noch mit einem künstlichen Kandidaten geprüft werden; im lokalen Test wird die
Transportgrenze ersetzt und die SQL-Routine mit echtem MySQL ausgeführt.

## Reproduzierbarer Test ohne Produktion

Voraussetzung: Docker und Python 3.11+. Kein Zugriff auf CodeWords, keine Tokens nötig.

Referenz und Katalog lassen sich ohne Dienststart mit
`python3 scripts/sync-service-artifacts.py --check` abgleichen bzw. ohne `--check`
neu erzeugen. Der Herkunftskopf wird erhalten; er muss die richtige Version nennen.

```bash
docker run -d --name codex-jobstep-intake-test-local --network none \
  --tmpfs /var/lib/mysql -e MYSQL_ALLOW_EMPTY_PASSWORD=yes \
  -e MYSQL_DATABASE=jobstep_test mysql:8.4
# Warten, bis MySQL bereit ist:
docker exec codex-jobstep-intake-test-local mysqladmin ping -u root
JOBSTEP_MYSQL_CONTAINER=codex-jobstep-intake-test-local \
  python3 -m unittest discover -s tests -v
docker rm -f codex-jobstep-intake-test-local
```

Der Test verweigert Container ohne Test-Namenspräfix, mit Netzwerk oder Host-Bind-Mounts.
Er verwendet ausschließlich die synthetische Fixture und darf seine Datenbank löschen.
Eine produktive Datenbankadresse ist kein Testparameter. Getestet werden reale
Service-Funktionen und echte MySQL-Transaktionen; Infrastruktur-Start auf Modulimport,
externer DB-Transport und URL-Abruf sind bewusst ausgeklammert.

## Rollback

Zuerst die alte Service-Version reaktivieren. Additive Spalten, Ersatzlinks und Routine
zunächst erhalten, ebenso den Schutz-Trigger; kein blindes DROP oder Löschen neuer Dokumente. Ein älterer Dienst
kennt Ersatzlinks nicht und kann alte Status zusammenfassen: im Rollback-Fall automatische
Ersatzaufnahmen pausieren und betroffene Vorgänge manuell prüfen. Für vorhandene Links
ist ein späteres Entfernen der Spalten eine eigene Datenmigration.

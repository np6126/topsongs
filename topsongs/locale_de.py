"""German versions of the messages passed to i18n.t(), keyed by the English text.

tests/test_i18n.py checks that every t() message has an entry here and that
both versions use the same placeholders.
"""
from __future__ import annotations

GERMAN: dict[str, str] = {
    # cli.py
    "Builds one playlist per artist for every Jellyfin user from the Last.fm top tracks, "
    "replacing the playlists of the previous run. Configured through environment variables "
    "or appdata/.env.": "Baut für jeden Jellyfin-Benutzer je Artist eine Playlist aus den "
    "Last.fm-Top-Tracks und ersetzt dabei die Playlists des Vorlaufs. Konfiguriert wird über "
    "Umgebungsvariablen bzw. appdata/.env.",
    "Also available as run-topsongs.": "Identisch aufrufbar als run-topsongs.",
    "Only plan and log the run, without changing playlists in Jellyfin. Overrides DRY_RUN "
    "from the configuration.": "Lauf nur planen und protokollieren, ohne Playlists in "
    "Jellyfin zu ändern. Überschreibt DRY_RUN aus der Konfiguration.",
    # live.py
    "'{artist}' is ambiguous at setlist.fm. Please choose the right artist.": (
        "'{artist}' ist bei setlist.fm nicht eindeutig. Bitte den richtigen Künstler wählen."
    ),
    "SETLISTFM_API_KEY is not set; live playlists are off.": (
        "SETLISTFM_API_KEY ist nicht gesetzt; Live-Playlists sind aus."
    ),
    "'{artist}' is not in {user}'s library.": "'{artist}' ist nicht in der Bibliothek von {user}.",
    "setlist.fm knows no artist '{artist}'.": "setlist.fm kennt keinen Künstler '{artist}'.",
    "There is no concert no. {number} (1–{count}).": (
        "Konzert Nr. {number} gibt es nicht (1–{count})."
    ),
    "Concert no. {number} has no setlist yet.": "Konzert Nr. {number} hat noch keine Setlist.",
    "No concerts selected.": "Keine Konzerte ausgewählt.",
    "At most {max} concerts per mix.": "Höchstens {max} Konzerte pro Mix.",
    "No setlist yet: {concerts}": "Noch keine Setlist: {concerts}",
    "Concert": "Konzert",
    "Mix of {count} concerts": "Mix aus {count} Konzerten",
    "Setlists from setlist.fm:": "Setlist-Daten von setlist.fm:",
    "Songs played at {share} % of the concerts or more, most played first.": (
        "Songs aus mindestens {share} % der Konzerte, die meistgespielten zuerst."
    ),
    "The playlist name is empty.": "Der Playlist-Name ist leer.",
    "None of the songs is in the library; no playlist created.": (
        "Keiner der Songs ist in der Bibliothek; keine Playlist angelegt."
    ),
    "The live tag is missing, so prune and purge do not protect it: {error}": (
        "Live-Tag fehlt, Prune und Purge schützen sie nicht: {error}"
    ),
    "The description with the setlist.fm source is missing: {error}": (
        "Beschreibung mit setlist.fm-Quelle fehlt: {error}"
    ),
    "Playlist created.": "Playlist angelegt.",
    # live_cli.py
    "Creates a Jellyfin playlist from a concert or a mix of the last concerts (setlist.fm). "
    "Never deletes or replaces anything.": "Legt aus einem Konzert oder einem Mix der letzten "
    "Konzerte (setlist.fm) eine Jellyfin-Playlist an. Löscht und ersetzt nie etwas.",
    "Artist from the library. May be left out with --setlist.": (
        "Künstler aus der Bibliothek. Ohne Angabe nur mit --setlist."
    ),
    "Only list the last 20 concerts, numbered.": "Nur die letzten 20 Konzerte nummeriert anzeigen.",
    "Mix of the last N concerts with a setlist (1–{max}). Default: 1.": (
        "Mix aus den letzten N Konzerten mit Setlist (1–{max}). Standard: 1."
    ),
    "Concerts by their number from --list, comma-separated (e.g. 1,3,4).": (
        "Konzerte nach ihrer Nummer aus --list, kommagetrennt (z.B. 1,3,4)."
    ),
    "A specific concert by its setlist.fm id or link. Can be repeated.": (
        "Bestimmtes Konzert per setlist.fm-ID oder -Link. Mehrfach angebbar."
    ),
    "Only concerts of this tour (setlist.fm search).": (
        "Nur Konzerte dieser Tour (Suche bei setlist.fm)."
    ),
    "Only concerts from this year.": "Nur Konzerte aus diesem Jahr.",
    "Only concerts at this venue.": "Nur Konzerte in dieser Venue.",
    "Only concerts in this city.": "Nur Konzerte in dieser Stadt.",
    "Only concerts in this country (country code, e.g. DE).": (
        "Nur Konzerte in diesem Land (Ländercode, z.B. DE)."
    ),
    "With --last: count only the newest night when a venue was played several times.": (
        "Mit --last: bei mehreren Abenden in einer Venue nur den neuesten zählen."
    ),
    "Mix: a song must have been played at this percentage of the concerts or more. "
    "Default: 50.": "Mix: ein Song muss in mindestens so vielen Prozent der Konzerte "
    "vorkommen. Standard: 50.",
    "Own playlist name instead of the suggested one.": (
        "Eigener Playlist-Name statt des automatischen."
    ),
    "Jellyfin user to create the playlist for; repeat or separate with commas for several. "
    "Default: the first active user.": "Jellyfin-Benutzer, für den die Playlist entsteht; "
    "mehrfach oder kommagetrennt für mehrere. Standard: erster aktiver.",
    "A copy for every active user.": "Eine Kopie für jeden aktiven Benutzer.",
    "One playlist every user sees, owned by --user or the first active user.": (
        "Eine Playlist, die alle Benutzer sehen; sie gehört --user oder dem ersten aktiven."
    ),
    "The artist's MusicBrainz id, when setlist.fm does not know the name uniquely.": (
        "MusicBrainz-ID des Künstlers, falls setlist.fm den Namen nicht eindeutig kennt."
    ),
    "Only show the preview, create nothing.": "Nur die Vorschau zeigen, nichts anlegen.",
    "Create without asking.": "Ohne Rückfrage anlegen.",
    "--pick expects numbers like 1,3,4, not '{value}'.": (
        "--pick erwartet Nummern wie 1,3,4, nicht '{value}'."
    ),
    "Give an artist or use --setlist.": "Künstler angeben oder --setlist verwenden.",
    "--last must be between 1 and {max}.": "--last muss zwischen 1 und {max} liegen.",
    "--min-share must be between 0 and 100.": "--min-share muss zwischen 0 und 100 liegen.",
    "--public makes one playlist for everyone: at most one --user, no --all-users.": (
        "--public legt eine Playlist für alle an: höchstens ein --user, kein --all-users."
    ),
    "Choose one with --mbid:": "Mit --mbid wählen:",
    "User '{name}' not found or disabled.": "Benutzer '{name}' nicht gefunden oder deaktiviert.",
    "No matching Jellyfin user found.": "Kein passender Jellyfin-Benutzer gefunden.",
    "Jellyfin is not reachable:": "Jellyfin nicht erreichbar:",
    "The setlists are by different artists.": "Die Setlists stammen von verschiedenen Künstlern.",
    "Public: one playlist every user sees, owned by {user}.": (
        "Öffentlich: eine Playlist, die alle Benutzer sehen; sie gehört {user}."
    ),
    "For: {users}": "Für: {users}",
    "Dry run: nothing created.": "Dry-Run: nichts angelegt.",
    "Without a terminal only with --yes.": "Ohne Terminal nur mit --yes.",
    "Create the playlist? [y/N] ": "Playlist anlegen? [j/N] ",
    "Cancelled, nothing created.": "Abgebrochen, nichts angelegt.",
    "Created:": "Angelegt:",
    "{name} with {count} songs for {user}.": "{name} mit {count} Songs für {user}.",
    "setlist.fm has no matching concerts by {artist}.": (
        "setlist.fm hat keine passenden Konzerte von {artist}."
    ),
    "{artist} · last concerts (setlist.fm)": "{artist} · letzte Konzerte (setlist.fm)",
    "No.": "Nr",
    "Date": "Datum",
    "Country": "Land",
    "none yet": "noch keine",
    "1 concert": "1 Konzert",
    "{count} concerts": "{count} Konzerte",
    "played": "gespielt",
    "Library": "Bibliothek",
    "encore": "Zugabe",
    "cover of {artist}": "Cover von {artist}",
    "✗ missing": "✗ fehlt",
    "Played at fewer than {share} % of the concerts: {songs}": (
        "Seltener als {share} % der Konzerte: {songs}"
    ),
    "{matched} of {total} songs in the library. Name: {name}": (
        "{matched} von {total} Songs in der Bibliothek. Name: {name}"
    ),
    # missing_cli.py, missing_report.py
    "Shows which songs of an artist are missing from the Jellyfin library.": (
        "Zeigt, welche Songs eines Künstlers in der Jellyfin-Bibliothek fehlen."
    ),
    "Artist name. Without one, every artist in the library is checked.": (
        "Künstlername. Ohne Angabe werden alle Künstler der Bibliothek geprüft."
    ),
    "Jellyfin user whose library is checked. Default: the first active one.": (
        "Jellyfin-Benutzer, dessen Bibliothek geprüft wird. Standard: erster aktiver."
    ),
    "Include compilations and live albums too (left out otherwise).": (
        "Auch Compilations und Live-Alben einbeziehen (sonst ausgeschlossen)."
    ),
    "Ignore the discography cache and load fresh from Last.fm.": (
        "Den Diskografie-Cache ignorieren und frisch von Last.fm laden."
    ),
    "Jellyfin error: {error}": "Jellyfin-Fehler: {error}",
    "Loading discography: {artist}…": "Lade Diskografie: {artist}…",
    "Last.fm error: {error}": "Last.fm-Fehler: {error}",
    "Could not load the artists:": "Künstler konnten nicht geladen werden:",
    "No artists to check.": "Keine Künstler zu prüfen.",
    "Checking {count} artists for user {user} (source: Last.fm)…": (
        "Prüfe {count} Künstler für Benutzer {user} (Quelle: Last.fm)…"
    ),
    "no albums found on Last.fm": "keine Alben auf Last.fm gefunden",
    "albums": "Alben",
    "tracks": "Tracks",
    "artists": "Künstler",
    "albums complete": "Alben komplett",
    "Total": "Gesamt",
    # providers/setlistfm.py
    "Not a setlist.fm setlist id or link: {value}": (
        "Keine setlist.fm-Setlist-ID oder -URL: {value}"
    ),
    "setlist.fm has no setlist {id}.": "Setlist {id} gibt es bei setlist.fm nicht.",
    "setlist.fm is not reachable: {error}": "setlist.fm nicht erreichbar: {error}",
    "setlist.fm rejects the API key (check SETLISTFM_API_KEY).": (
        "setlist.fm lehnt den API-Key ab (SETLISTFM_API_KEY prüfen)."
    ),
    "setlist.fm limit reached (2 requests a second, 1,440 a day). Try again later.": (
        "setlist.fm-Limit erreicht (2 Abfragen pro Sekunde, 1.440 pro Tag). "
        "Später erneut versuchen."
    ),
    "setlist.fm answers with HTTP {status}.": "setlist.fm antwortet mit HTTP {status}.",
    # prune_cli.py, purge_cli.py
    "Keeps only the playlists named with --keep and deletes all others, across ALL Jellyfin "
    "users. Kept ones can be renamed with --rename-prefix.": "Behält nur die mit --keep "
    "genannten Playlists und löscht alle anderen — über ALLE Jellyfin-Benutzer. Behaltene "
    "können mit --rename-prefix umbenannt werden.",
    "Name of a playlist to keep. Repeat or separate with commas "
    "(e.g. --keep Alice --keep Bob or --keep Alice,Bob). Required.": "Name einer zu "
    "behaltenden Playlist. Mehrfach oder kommagetrennt "
    "(z.B. --keep Alice --keep Bob oder --keep Alice,Bob). Pflicht.",
    "Prefix to rename kept playlists with (e.g. '_'). Default: none.": (
        "Prefix, mit dem behaltene Playlists umbenannt werden (z.B. '_'). Standard: keiner."
    ),
    "Only show what would happen, without changing anything.": (
        "Nur anzeigen, was passieren würde, ohne etwas zu verändern."
    ),
    "Run without asking.": "Ohne interaktive Rückfrage ausführen.",
    "Could not load the playlists of {user}, skipped:": (
        "Playlists für '{user}' nicht ladbar, übersprungen:"
    ),
    "{count} playlists will be deleted irrevocably.": (
        "{count} Playlists werden unwiderruflich gelöscht."
    ),
    "Type 'yes' to confirm: ": "Zum Bestätigen 'ja' eingeben: ",
    "No --keep given — that would delete ALL playlists.": (
        "Kein --keep angegeben — das würde ALLE Playlists löschen."
    ),
    "Aborted.": "Abbruch.",
    "{users} users, {count} playlists (unique by id).": (
        "{users} Benutzer, {count} Playlists (eindeutig nach id)."
    ),
    "KEEP ({count}):": "BEHALTEN ({count}):",
    "already fine": "schon ok",
    "PROTECTED ({count}):": "GESCHÜTZT ({count}):",
    "live playlists, always kept": "Live-Playlists, bleiben immer",
    "DELETE ({count}):": "LÖSCHEN ({count}):",
    "Note: no match for --keep: {names}": "Hinweis: kein Treffer für --keep: {names}",
    "Dry run:": "Dry-Run:",
    "{delete} would be deleted, {rename} renamed, {keep} kept. Nothing changed.": (
        "{delete} würden gelöscht, {rename} umbenannt, {keep} behalten. Nichts verändert."
    ),
    "Nothing to do.": "Nichts zu tun.",
    "Cancelled. Nothing changed.": "Abgebrochen. Nichts verändert.",
    "{renamed} renamed, {deleted} deleted": "{renamed} umbenannt, {deleted} gelöscht",
    "{rename} rename errors, {delete} delete errors": (
        "{rename} rename-Fehler, {delete} delete-Fehler"
    ),
    "{count} kept.": "{count} behalten.",
    "Could not rename {name}:": "Umbenennen fehlgeschlagen für '{name}':",
    "Could not delete {name}:": "Löschen fehlgeschlagen für '{name}':",
    "Deletes the nightly run's playlists (recognized by the PLAYLIST_MANAGED_TAG tag) for "
    "ALL Jellyfin users. Never live playlists.": "Löscht die Playlists des nächtlichen "
    "Laufs (erkannt am Tag PLAYLIST_MANAGED_TAG) für ALLE Jellyfin-Benutzer. "
    "Live-Playlists nie.",
    "Instead, delete every playlist whose name starts with this (except live ones).": (
        "Stattdessen alle Playlists löschen, deren Name so beginnt (außer Live-Playlists)."
    ),
    "Only show what would be deleted, without changing anything.": (
        "Nur anzeigen, was gelöscht würde, ohne etwas zu verändern."
    ),
    "Delete without asking.": "Ohne interaktive Rückfrage löschen.",
    "tag '{tag}'": "Tag '{tag}'",
    "prefix '{prefix}'": "Präfix '{prefix}'",
    "The prefix is empty — a purge would delete ALL playlists.": (
        "Prefix ist leer — ein Purge würde ALLE Playlists löschen."
    ),
    "No playlists with {selection} found.": "Keine Playlists mit {selection} gefunden.",
    "Found {count} playlists with {selection} across {users} users.": (
        "Gefunden: {count} Playlists mit {selection} über {users} Benutzer."
    ),
    "{count} playlists would be deleted. Nothing was changed.": (
        "{count} Playlists würden gelöscht. Nichts wurde verändert."
    ),
    "Cancelled. Nothing was deleted.": "Abgebrochen. Nichts wurde gelöscht.",
    "{count} deleted": "{count} gelöscht",
    "{count} failed": "{count} fehlgeschlagen",
    # web
    "Invalid or missing token.": "Ungültiges oder fehlendes Token.",
    "A playlist refresh is already running.": "Ein Playlist-Lauf läuft bereits.",
    "No keep list — that would delete ALL playlists.": (
        "Keine Keep-Liste — das würde ALLE Playlists löschen."
    ),
    "set": "gesetzt",
    "not set": "nicht gesetzt",
}

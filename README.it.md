# ClanBoard

[![ci](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

Bot Telegram per i clan di Clash of Clans, in 20 lingue. Segue le guerre, la CWL, la Capitale, i
Giochi del Clan, chi entra e chi esce, e racconta al gruppo del clan quello che succede, con il
tabellone della guerra fissato in alto. I capi ricevono promemoria, bersagli, classifiche, titoli
del clan e il riepilogo della settimana. È tutto gratis e niente si sblocca pagando.

[Read me in English](README.md)

## Portalo nel tuo clan

Scrivi `/newbot` con il tag del tuo clan al bot console di ClanBoard su Telegram, conferma nella
finestra di Telegram, poi porta il bot nuovo nel gruppo del clan. Solo i capi e i vicecapi
verificati possono creare un bot, e c'è un bot per clan. Nel gruppo il bot tiene una bacheca fissata e parla solo per gli urgenti della guerra. Dal bottone della bacheca ognuno apre dentro Telegram la sua Mini App: bacheca, guerra, i suoi dati, e per chi gestisce il clan le impostazioni, il registro e gli strumenti.

## Ospitalo tu

Clona questo repository, poi, dentro:

```
docker compose up -d db
docker compose run --rm bot setup
docker compose up -d
```

`setup` chiede, e salva cifrate nel database, le cose che riguardano la tua copia: il token
Telegram di BotFather, una o più chiavi dell'API di Clash of Clans, l'indirizzo pubblico del
codice sorgente della tua copia, che la licenza richiede, e l'id Telegram che riceve gli avvisi.
Gli ultimi due si saltano con una risposta vuota e si mettono dopo con `secret source_url` e
`secret owner_id`: l'indirizzo di solito esiste solo dopo che hai pubblicato la tua copia. Non c'è
nessun file di configurazione, né ora né mai.

La Mini App vuole due cose in più: l'indirizzo pubblico del servizio in `secret site_base` e la
registrazione dell'app sul bot console della tua copia, da fare una volta sola su BotFather. Senza,
tutto il resto funziona uguale e il fissato resta senza bottone: i passi esatti sono nella pagina
«Ospita la tua copia» del sito.

## Gestione

Ogni comando si dà dal terminale e non scrive niente in chiaro:

```
docker compose run --rm bot secret <kind>
docker compose run --rm bot addbot
docker compose run --rm bot addclan
docker compose run --rm bot status
docker compose run --rm bot retention --dry-run
```

Due voci vale la pena chiamarle per nome: `secret channel_url` tiene l'indirizzo della community
ufficiale, il link che la home e `/support` mostrano quando c'è, e `secret otp_reset`, con lo
username o l'id Telegram di un gestore, toglie dal server il codice dell'Authenticator di quella
persona. È l'unica via di rientro quando il telefono con i codici non c'è più, e si dà sulla
macchina, mai da una chat.

`ops/vps/backup.sh` prende il dump del database, copia la chiave master e applica la ritenzione;
`ops/vps/guard.sh` guarda i container, l'età dell'ultimo dump, quanto pesa il database e gli
errori nel log, e scrive al proprietario quando qualcosa non torna. Vanno fatti girare a orario
dalla macchina che ospita la tua copia, che resta fuori da questo repository.

## Lingue

20 lingue, l'inglese come sorgente e come riserva: sono in `clashbot/locales/`. Un clan sceglie la
sua con `/lang`; nelle chat private il bot segue la lingua del tuo Telegram. Sistemare una
traduzione è il modo più facile di contribuire: vedi [CONTRIBUTING.md](CONTRIBUTING.md).

Una pull request si firma una volta sola, dentro la pull request stessa, con l'accordo per i
contributori in [CLA.md](CLA.md).

## Cosa salva, e per quanto

I dati pubblici del gioco presi dall'API ufficiale di Clash of Clans, più quello che il clan
scrive attraverso il bot: il collegamento fra un account Telegram e il tag di un giocatore per chi
si collega con `/link`, le note dei capi, le candidature. Tutto quello che tiene è salvato cifrato
con AES-GCM; la chiave master vive in un volume a parte, mai nel database e mai nel repository. Le
guerre si tengono 100 per clan, i clan disattivati si cancellano dopo 90 giorni con tutto quello
che gli sta appeso, e le chiavi con una scadenza se ne vanno con la stessa pulizia. `/unlink`
toglie il tuo collegamento.

## Sicurezza

Ogni abuso che ci aspettiamo ha una difesa nel codice e un test che si rompe se la difesa sparisce.
La lista di controllo è in [docs/sicurezza.md](docs/sicurezza.md): una riga per minaccia, con il
controllo e il nome del test che lo dimostra.

## Chi lo mantiene

Alexandru Bumbac · GitHub @drjackal9

## Licenza

ClanBoard · Copyright (C) 2026 Alexandru Bumbac (@drjackal9) · AGPL-3.0, vedi [LICENSE](LICENSE).

Far girare una copia modificata che le persone raggiungono in rete vuol dire pubblicare il tuo
sorgente e metterne l'indirizzo con `secret source_url`: il bot lo mostra in `/support`.

## Clash of Clans

Questo materiale non è ufficiale e non è approvato da Supercell. Per maggiori informazioni vedi la Fan Content Policy di Supercell: www.supercell.com/fan-content-policy

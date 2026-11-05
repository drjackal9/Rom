# Sicurezza

## Come si segnala

Con la segnalazione privata di sicurezza di GitHub, sul repository: scheda Security, poi
"Report a vulnerability". Resta fra chi segnala e chi mantiene il progetto, Alexandru Bumbac (GitHub
@drjackal9), finché non è sistemata.

Un problema di sicurezza non si racconta mai in pubblico: niente issue aperte, niente pull request
che mostrano il buco, niente messaggi nei gruppi del bot.

## Che cosa non va mai in una segnalazione

Token, chiavi dell'API, dump del database, il contenuto del volume delle chiavi. La segnalazione
descrive il problema e i passi per rifarlo; se serve altro lo chiede chi risponde, per la via
privata.

## Portata

Dentro: il codice di questo pacchetto e l'istanza ufficiale. Fuori: il gioco e la sua API,
Telegram, e le copie modificate ospitate da altri, che rispondono a chi le ospita.

## Tempi

Prima risposta appena possibile, indicativamente entro sette giorni. Se dopo quattordici giorni non
è arrivata nessuna risposta, chi ha segnalato può aprire una segnalazione pubblica **senza dettagli
tecnici** per sollecitare.

## Ringraziamento pubblico

Chi segnala per la via privata e aspetta la correzione viene ringraziato in pubblico, con il nome
che sceglie lui, in [docs/ringraziamenti.md](docs/ringraziamenti.md); chi preferisce restare senza
nome resta senza nome. Non ci sono premi in denaro: nessun programma di ricompense, niente promesso
e niente pagato. La home del sito invita a segnalare prima e porta alla lista.

## Come è fatto il progetto

Utile a chi guarda il codice cercando un appiglio:

- Nel repository non c'è nessun segreto, per costruzione: nessun file di configurazione, nessun
  `.env`, niente da dimenticare dentro un commit.
- Ogni segreto è cifrato con AES-GCM nel database e richiamato per alias; la chiave maestra vive in
  un volume separato, mai nel database e mai nel repository.
- I contenitori non pubblicano porte, e il database sta su una rete interna che non esce.
- Le ricerche passano da indici ciechi, HMAC della chiave maestra: si trova una riga senza tenere
  in chiaro la cosa cercata.

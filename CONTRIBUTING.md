# Contribuire a ClanBoard

Si contribuisce con una pull request. Sistemare una traduzione è il modo più facile di cominciare;
un cambiamento nel codice arriva con la sua prova.

## Come si prova

Dentro il repository:

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pyflakes clashbot tests
node tests/js/run.js
.venv/bin/python -m pytest -q -p no:cacheprovider tests
```

Le ultime tre righe sono le prove: devono essere verdi prima di aprire una pull request, e la CI
esegue esattamente quelle, niente di più e niente di diverso.

## Regole che la CI impone

- Niente commenti e niente docstring, in nessun linguaggio. Passano solo le direttive funzionali,
  quelle che uno strumento legge davvero, come `noqa`. Quello che c'è da spiegare si spiega nel
  messaggio del commit o nella pull request.
- Nessun file di configurazione e nessun `.env`. I segreti vivono cifrati nel database e si
  richiamano per alias; il comando `setup` li chiede e li salva, non li scrive mai su disco in
  chiaro.
- Mai un token, una chiave o l'indirizzo di una macchina in un file, in un test o nel testo di un
  errore, nemmeno finto e lungo: nei test si usano valori finti corti, e per gli indirizzi IP solo
  quelli che la RFC 5737 riserva alla documentazione.
- Dipendenze fissate con `==` e con una licenza compatibile con AGPL-3.0. Una dipendenza nuova
  arriva con la sua riga fissata e con la licenza detta nella pull request.

## Traduzioni

Una traduzione si propone qui, con una pull request sui cataloghi: il sito non ha un portale e non
esiste altra strada. Il gestore la fa viva unendo la pull request, e chi propone firma l'accordo
per i contributori dentro la pull request stessa, come per ogni altro contributo.

Il catalogo inglese è la sorgente, l'italiano è il secondo riferimento. Si modifica
`clashbot/locales/<lingua>.json` **solo sulle righe che cambiano**, mai riscrivendo il file con uno
strumento: le chiavi restano nello stesso ordine dell'inglese, l'indentazione è di due spazi e il
file finisce con un a capo. Una chiave nuova va in fondo a tutti e 20 i file, con il testo vero in
inglese e in italiano e l'inglese nelle altre lingue, finché la traduzione non arriva.

La prova di questa sezione:

```
.venv/bin/python -m pytest -q tests/test_locales.py
```

## Un cambiamento nel codice

Un commit per passo logico, con i percorsi scritti uno per uno e un messaggio che dice cosa
cambia. Prima il test che fallisce, poi il codice che lo fa passare. Una funzione si consegna
accesa: niente pezzi spenti dietro un interruttore da confermare dopo.

## Accordo per i contributori

Il progetto esce sotto AGPL-3.0, la licenza del progetto: vedi [LICENSE](LICENSE). Chi contribuisce
firma in più l'accordo in [CLA.md](CLA.md), che cede al titolare i diritti economici sul contributo
e il diritto di rilicenziarlo anche sotto una licenza diversa, concede una licenza sui brevetti e
dichiara che il contributo è opera originale di chi lo manda. Serve perché con AGPL-3.0 il codice di
altri resterebbe legato a quella licenza per sempre: l'accordo tiene aperta la strada a una licenza
diversa senza dover rintracciare uno per uno chi ha contribuito. Chi contribuisce per una società o
un'associazione firma la versione per l'ente, che vale per tutte le sue persone. Il testo è un
modello e lo dice: prima del primo contributo esterno va fatto controllare da un legale.

Si firma una volta sola e si firma dentro la pull request, senza mandare niente a nessuno: un bot
commenta chiedendo la firma, si risponde con la frase che il commento mostra, e la firma resta nel
ramo `cla-signatures` di questo repository, nel file `signatures/cla.json`. Finché non c'è, la pull
request resta bloccata; quando c'è, vale anche per tutte quelle che apri dopo.

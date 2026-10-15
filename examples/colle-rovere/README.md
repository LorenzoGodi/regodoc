# Pacchetto .regodoc: Rinnovo della rete della Cantina Colle Rovere

Questo file lo scrive il motore regodoc a ogni esportazione. Quando il pacchetto torna
indietro non conta, e ciò che vi si modifica va perso.

## Che cosa contiene

- `structure.toml`: intestazione, lingua e ordine delle parti;
- `variables.toml`: i valori nominati, come date, importi e quantità;
- `parts/`: il testo, un file XML per apertura o per parte, con il nome del suo id;
- `images/`: le figure, solo PNG o JPEG;
- `manifest.json` e `mimetype`: la busta, che scrive il motore.

## Come modificarlo

1. modifica `structure.toml`, `variables.toml` e i file in `parts/`, sempre in UTF-8;
2. metti le immagini in `images/` e richiamale nel testo con `<figure file="images/…"/>`;
3. controlla il pacchetto con `regodoc validate` e ricostruisci l'archivio con
   `regodoc canon`.

Le regole del formato sono nella specifica `rego/1` del progetto regodoc:
https://github.com/LorenzoGodi/regodoc/blob/main/docs/spec/rego-1.md

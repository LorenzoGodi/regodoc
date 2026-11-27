# Rinnovo della rete della Cantina Colle Rovere

Una sintesi per la direzione: la rete degli uffici è **da sostituire**, le copie di
sicurezza vanno rese automatiche.

## Rete e collegamenti

### Rete locale

Le postazioni di ufficio e di laboratorio passano da un apparato centrale di *vecchia
generazione*; il nome interno del dominio resta `colle-rovere.example`.

- dodici postazioni fisse
- due stampanti di rete
  - una a colori, in amministrazione
- quattro punti di accesso senza fili

#### Copertura senza fili

La barricaia è coperta solo in parte: oltre la seconda fila di botti il segnale è debole.

![Copertura misurata prima dei lavori](images/coverage.png)

### Apparati da sostituire

| Apparato | Anni | Costo stimato |
|---|--:|--:|
| commutatore centrale | 9 | 1.800 € |
| punti di accesso | 7 | 1.200 € |

## Copie di sicurezza

1. una copia ogni notte sul NAS, alle 2;
2. una copia settimanale fuori sede;
3. una prova di ripristino ogni mese.

```
rsync -a --delete /dati/ nas:/copie/notte/
```

"""Permette di chiamare il motore con ``python -m regodoc``."""

import os

try:
    from regodoc.cli import main
except MemoryError:
    # Anche prima del comando, mentre si caricano i moduli: niente traceback, ma il codice
    # d'ambiente e la stessa riga fissa che cli scrive quando non può scrivere il rapporto.
    os.write(2, b"regodoc: memoria esaurita\n")
    raise SystemExit(3) from None

raise SystemExit(main())

"""Permette di chiamare il motore con ``python -m regodoc``."""

import contextlib
import os

try:
    from regodoc.cli import main
except MemoryError:
    # Anche prima del comando, mentre si caricano i moduli: niente traceback, ma il codice
    # d'ambiente e la stessa riga fissa che cli scrive quando non può scrivere il rapporto;
    # con stderr chiuso resta il codice.
    with contextlib.suppress(OSError):
        os.write(2, b"regodoc: memoria esaurita\n")
    raise SystemExit(3) from None

raise SystemExit(main())

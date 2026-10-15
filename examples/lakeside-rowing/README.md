# .regodoc package: Records and equipment of the Lakeside Rowing Club

The regodoc engine writes this file on every export. It is ignored when the package is
read back, and anything changed here is lost.

## What it contains

- `structure.toml`: header, language and order of the parts;
- `variables.toml`: the named values, such as dates, amounts and quantities;
- `parts/`: the text, one XML file per opening or part, named after its id;
- `images/`: the figures, PNG or JPEG only;
- `manifest.json` and `mimetype`: the envelope, written by the engine.

## How to change it

1. edit `structure.toml`, `variables.toml` and the files in `parts/`, always in UTF-8;
2. put the images in `images/` and refer to them in the text with
   `<figure file="images/…"/>`;
3. check the package with `regodoc validate` and rebuild the archive with
   `regodoc canon`.

The format is described in the `rego/1` specification of the regodoc project:
https://github.com/LorenzoGodi/regodoc/blob/main/docs/spec/rego-1.md

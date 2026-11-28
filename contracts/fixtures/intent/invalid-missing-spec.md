# Catalog

Paths: `src/catalog/`, `config/catalog.toml`

## End user

Readers browse a local catalog to find public documents.

## Performance goals

Catalog search returns results within one second for a thousand entries.

## Security boundaries

Catalog search reads only the published index.

## Why the optimizations exist

The index stores normalized titles so searches can reuse them.

## Cost concerns

The index uses at most ten megabytes of local storage.

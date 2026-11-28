# Catalog previews

Spec: #42

## End user

Readers use previews to identify documents before opening them.

## Performance goals

A preview opens within one second from the local catalog.

## Security boundaries

Previews contain only fields from public catalog entries.

## Why the optimizations exist

The catalog reuses generated previews so repeated opens avoid rendering.

## Cost concerns

none: Previews use the existing storage allocation.

## Related

- `docs/adr/0001-catalog-previews.md`
- `docs/intent/catalog.md`

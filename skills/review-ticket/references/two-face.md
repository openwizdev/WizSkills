# Review both faces of an interface

Apply both checks to each changed interface wherever an agent reads or writes it or a person sees it. Report each gap under Spec and [grade it by its impact](verdict.md#two-faces).

## Agent face

- Find the machine-first, versioned contract file and its schema.
- Find the fixtures and run the test that exercises them.
- Check that records have exact forms. A caller can tell which fields are required, what values they accept and how to read or write each record. A prose-only interface or a field the caller has to guess is a finding.

**Synthetic pass.** A pantry exporter writes `pantry.snapshot/1` records. Its versioned contract and schema define the exact fields and types. The exporter test runs valid and invalid fixtures and checks them against the schema.

**Synthetic fail.** A pantry importer reads `pantry.order/1` records. A versioned contract and an exercised fixture show the record form, but there is no schema. Report the missing schema even if the sample record imports successfully.

## Human face

- Check the evidence for screenshots at 390 and 1440 px.
- Check that the screen is readable at a glance and offers one clear next action.
- Check that the evidence shows the empty, loading, unavailable and error states. Report a missing screenshot or state.
- Check keyboard operation, focus order, screen-reader labels and announcements, and readable contrast.
- Check that each error states the exact fact and gives the next command.

**Synthetic pass.** A pantry restock view has evidence at both widths for all four states. The labelled controls work by keyboard in reading order, status changes are announced, and text has readable contrast. The failure state says the inventory file is missing and offers `pantry init` as the next command.

**Synthetic fail.** A pantry order view has screenshots at both widths, but the list is blank when there are no orders. Report the missing empty state. A person opening the list for the first time has no way to tell what happened or what to do next.

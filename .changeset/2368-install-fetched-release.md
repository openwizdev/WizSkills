---
"install": patch
---

The install skill installs the release it fetches: preflight clones that release's tag, the fallback fetches its files, and the done check expects its version; 0.1.0 stays installable by naming its tag. The restart and resume checks read the skill's own version, so a release bump no longer stops the install.

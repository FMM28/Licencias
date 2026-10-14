// Copia las fuentes (solo el subconjunto latino, suficiente para español) a los estáticos del panel.
// Se sirven desde el propio servidor: el CSP del panel no permite cargar nada de terceros.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "..", "app", "web", "static", "fonts");
mkdirSync(out, { recursive: true });

for (const family of ["atkinson-hyperlegible-next", "atkinson-hyperlegible-mono"]) {
  const file = `${family}-latin-wght-normal.woff2`;
  copyFileSync(join(root, "node_modules", "@fontsource-variable", family, "files", file),
               join(out, file));
  console.log("fuente:", file);
}

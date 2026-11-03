/** El usuario como se muestra: con mayúscula al principio de cada parte ("nvazzoler" → "Nvazzoler", "ana.paz" → "Ana.Paz"). */
export function persona(usuario: string | null | undefined): string {
  return (usuario ?? "").replace(/(^|[\s._-])(\p{L})/gu, (_, antes: string, letra: string) => antes + letra.toUpperCase());
}

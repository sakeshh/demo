/** User-facing label for backend `source_root` (blob prefix, DB marker, paths). */
export function sourceRootLabel(sourceRoot?: string): string {
  const sr = String(sourceRoot || '').trim();
  if (!sr) return '';

  if (sr.startsWith('__database__')) {
    const label = sr.includes(':') ? sr.split(':', 2)[1] : '';
    return `Azure SQL${label ? ` (${label})` : ''}`;
  }

  if (sr === 'azure_blob' || sr.startsWith('azure_blob:')) {
    const prefix = sr.startsWith('azure_blob:') ? sr.slice('azure_blob:'.length).trim() : '';
    return `Azure Blob${prefix ? ` (${prefix})` : ''}`;
  }

  return `Filesystem (${sr})`;
}

export function humanizeSnakeIdentifier(value?: string): string {
  const t = String(value || '').trim();
  if (!t) return '';
  if (!t.includes('_')) {
    return t.length === 1 ? t.toUpperCase() : t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
  }
  return t
    .split('_')
    .map((part) => (part.length ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : ''))
    .filter(Boolean)
    .join(' ');
}

export function humanizeSeverityLabel(value?: string): string {
  const t = String(value || '').trim();
  if (!t) return '';
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}

export function prettyTableHeaderKey(key: string): string {
  if (!key) return '';
  if (!key.includes('_')) return key.charAt(0).toUpperCase() + key.slice(1);
  return humanizeSnakeIdentifier(key);
}

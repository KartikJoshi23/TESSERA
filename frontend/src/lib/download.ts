/** Hand the viewer a file. It is only ever a masked trace, as stored in the event log. */
export function saveJson(name: string, value: unknown): void {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 1)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name.replaceAll(/[^\w.-]/g, "_");
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

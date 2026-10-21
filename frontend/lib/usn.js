const USN_PATTERN = /^01FE\d{2}(?:BCS|BEE|BEC|BEV|BCI|BME)\d{3}$/;

export function normalizeUsn(value) {
  return value.trim().toUpperCase();
}

export function isValidUsn(value) {
  return USN_PATTERN.test(normalizeUsn(value));
}

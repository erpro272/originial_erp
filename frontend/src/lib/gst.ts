/** GSTIN checks mirrored from the API (app/core/gst.py) for instant form feedback.
 * The server stays authoritative and re-validates everything. */
const B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export const STATES: Record<string, string> = {
  "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
  "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
  "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
  "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
  "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
  "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
  "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory",
}; // prettier-ignore

export function gstinChecksum(first14: string): string {
  let total = 0;
  for (let i = 0; i < 14; i++) {
    const p = B36.indexOf(first14[i]!) * (i % 2 === 0 ? 1 : 2);
    total += Math.floor(p / 36) + (p % 36);
  }
  return B36[(36 - (total % 36)) % 36]!;
}

export function gstinError(value: string): string | null {
  const g = value.trim().toUpperCase();
  if (!g) return null;
  if (g.length !== 15) return "GSTIN must be 15 characters.";
  if (!GSTIN_RE.test(g)) return "GSTIN format is invalid (e.g. 27AAACT2727Q1ZV).";
  if (!STATES[g.slice(0, 2)]) return `GSTIN state code ${g.slice(0, 2)} does not exist.`;
  if (gstinChecksum(g.slice(0, 14)) !== g[14])
    return "GSTIN checksum is invalid (check for a typo).";
  return null;
}

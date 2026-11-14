import { gstinError } from "./gst";

test("GSTIN validation matches the server's rules", () => {
  expect(gstinError("27AAPFU0939F1ZV")).toBeNull();
  expect(gstinError("29aagcb7383j1z4")).toBeNull();
  expect(gstinError("27AAPFU0939F1ZX")).toMatch(/checksum/);
  expect(gstinError("27AAPFU0939F1Z")).toMatch(/15 characters/);
  expect(gstinError("40AAPFU0939F1ZV")).toMatch(/state code/);
  expect(gstinError("")).toBeNull();
});

// Ready-made emails for the simulator, so a demo does not start from a blank page. Every company and person here is made up.

export type Sample = {
  id: string; label: string; expect: string;
  from: string; subject: string; body: string; si?: string; bl?: string;
};

const SI = `SHIPPING INSTRUCTION
========================================

Shipper/Exporter: NORTHWIND PAPER TRADING PTE LTD
  1 HARBOUR ROAD, #12-01; SINGAPORE 049213
CONSIGNEE: ACME STATIONERY LLC
  P.O. BOX 4412; DUBAI, UNITED ARAB EMIRATES
NOTIFY PARTY: ACME STATIONERY LLC
Port of Loading: SINGAPORE (SGSIN)
Discharge Port: KARACHI, PAKISTAN (PKKHI)
No. of Containers or Packages: 6 x 40'HC
Gross Weight (KG): 131,058 KG
Vessel Name: PACIFIC DAWN V.2609E
Booking Ref: SIN4471209
`;

const BL = `BILL OF LADING (DRAFT)
========================================

SHIPPER: NORTHWIND PAPER TRADING PTE LTD
  1 HARBOUR ROAD, #12-01; SINGAPORE 049213
CONSIGNEE: ACME STATIONERY LLC
  P.O. BOX 4412; DUBAI, UNITED ARAB EMIRATES
Notify: ACME STATIONERY LLC
Port of Loading (POL): SINGAPORE (SGSIN)
POD: KARACHI, PAKISTAN (PKKHI)
Container Count: 6 x 40'HC
Gross Wt (kgs): 131,058 KG
Vessel Name: PACIFIC DAWN V.2609E
Bill of Lading No.: OOLU7741200
`;

const check = (subject: string, body = "Dear team,\n\nAttached are the SI and the draft BL for checking. Please advise.\n\nThanks,\nOps") => ({
  from: "ops@northwind-paper.example", subject, body,
});

export const SAMPLES: Sample[] = [
  {
    id: "match", label: "Documents match", expect: "Verified automatically (OK)",
    ...check("Check draft BL vs SI - NW-4471 to Karachi"), si: SI, bl: BL,
  },
  {
    id: "labels", label: "Same shipment, different wording", expect: "OK: labels and units are mapped (tonnes become kg)",
    ...check("Check draft BL vs SI - NW-4472 to Karachi"),
    si: `SHIPPING INSTRUCTION

Shipper (Principal or Seller): NORTHWIND PAPER TRADING PTE LTD
Consignee (Non-Negotiable): ACME STATIONERY LLC
Notify Party/Intermediate Consignee: ACME STATIONERY LLC
Load Port: SINGAPORE
Destination Port: KARACHI, PAKISTAN
Total Containers: 3 x 20'FCL + 3 x 20'FCL
TOTAL Gross Wt (kgs): 131,058
`,
    bl: `BILL OF LADING (DRAFT)

Shipper/Exporter: NORTHWIND PAPER TRADING PTE LTD
To the Order of: ACME STATIONERY LLC
Notify Party: ACME STATIONERY LLC
Port of Loading: SINGAPORE
Port of Discharge: KARACHI, PAKISTAN
No. of Containers or Packages: 6 x 20'FCL
Gross Weight (KG): 131.058 MT
`,
  },
  {
    id: "mismatch", label: "Consignee and weight differ", expect: "Mismatch found: Consignee, Notify party, Gross weight",
    ...check("Check draft BL vs SI - NW-4473 to Karachi"), si: SI,
    bl: BL.replaceAll("ACME STATIONERY LLC", "ACME STATIONERY FZE").replace("131,058 KG", "113,058 KG"),
  },
  {
    id: "blank", label: "A value is blank on the SI", expect: "Needs a person: the system does not guess",
    ...check("Check draft BL vs SI - NW-4474 to Karachi"),
    si: SI.replace("NOTIFY PARTY: ACME STATIONERY LLC", "NOTIFY PARTY: ???"), bl: BL,
  },
  {
    id: "nobl", label: "BL not attached", expect: "Needs a person: missing attachment",
    ...check("Check draft BL vs SI - NW-4475 to Karachi", "Dear team,\n\nPlease check the SI against the draft BL (BL to follow).\n\nThanks,\nOps"), si: SI,
  },
  {
    id: "wrongdoc", label: "Wrong document attached", expect: "Needs a person: second attachment is not a BL",
    ...check("Check draft BL vs SI - NW-4476 to Karachi"), si: SI,
    bl: `COMMERCIAL INVOICE
Invoice No.: INV-88231
Seller: NORTHWIND PAPER TRADING PTE LTD
Buyer: ACME STATIONERY LLC
Total amount: USD 84,120.00
`,
  },
  {
    id: "invoice", label: "Invoice question (no documents)", expect: "Classified as INVOICE_QUERY only",
    from: "accounts@acme-stationery.example", subject: "Query on charges breakdown for invoice 5510239",
    body: "Hi,\n\nCould you send a breakdown of the local charges on invoice 5510239? The total looks higher than the quotation.\n\nRegards,\nAccounts",
  },
  {
    id: "spam", label: "Spam", expect: "Classified as SPAM only",
    from: "winner@lucky-prizes.example", subject: "You have been selected! Claim your reward now",
    body: "Congratulations!!! Click the link below within 24 hours to claim your free gift card. No purchase necessary.",
  },
];

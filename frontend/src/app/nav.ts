/** Top-level modules (slide 1 of the planning deck). Dashboard sits at the end. */
export interface ModuleNav {
  key: string;
  label: string;
  path: string;
  description: string;
  sections: string[];
  /** Which feature delivers it (shown on the Coming soon page). */
  plannedIn: string;
}

export const MODULES: ModuleNav[] = [
  {
    key: "orders",
    label: "Orders",
    path: "/orders",
    description: "Every order received, ranked by priority, plus the customer database.",
    sections: ["Orders received", "Customers", "Invoice upload"],
    plannedIn: "Feature 1",
  },
  {
    key: "planning",
    label: "Planning",
    path: "/planning",
    description: "Turn accepted orders into a feasible, costed manufacturing plan.",
    sections: [
      "Selected orders",
      "Manufacturing sequence",
      "Production schedule",
      "Resource feasibility",
      "Financial analysis",
      "Final plan approval",
    ],
    plannedIn: "Feature 2",
  },
  {
    key: "purchasing",
    label: "Purchasing",
    path: "/purchasing",
    description: "Inventory, raw material purchase and supplier comparison.",
    sections: ["Inventory", "Raw material purchase", "Suppliers"],
    plannedIn: "a later feature",
  },
  {
    key: "production",
    label: "Production",
    path: "/production",
    description: "Manufacturing progress on the plant floor, stock movement and deliveries.",
    sections: ["Manufacturing progress", "Stock movement", "Deliveries"],
    plannedIn: "a later feature",
  },
  {
    key: "billing",
    label: "Billing",
    path: "/billing",
    description: "Cash settlements, invoices, e-bills and GST filing.",
    sections: ["Cash settlements", "Invoices", "E-Bill", "GST filing"],
    plannedIn: "a later feature",
  },
  {
    key: "finance",
    label: "Finance",
    path: "/finance",
    description: "Sales analysis, expenses and profit.",
    sections: ["Sales", "Expenses", "Profit"],
    plannedIn: "a later feature",
  },
  {
    key: "dashboard",
    label: "Dashboard",
    path: "/dashboard",
    description: "One overview across every module.",
    sections: [],
    plannedIn: "a later feature",
  },
];

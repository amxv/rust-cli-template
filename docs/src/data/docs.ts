// Bootstrap edits only this identity block; prose pages remain project-owned.
const generatedIdentity = {
  name: "mycli",
  strapline: "A Rust CLI ready to ship",
  description:
    "Documentation for mycli, a Rust command-line starter with tests, dist-powered releases, npm installation, and an isolated docs site.",
  repoUrl: "https://github.com/amxv/rust-cli-template",
  footerText: "A Rust CLI with build, release, installer, and documentation plumbing ready from the first commit.",
  distributionText: "GitHub Releases and npm packages are driven by dist."
} as const;

export const siteConfig = {
  name: generatedIdentity.name,
  strapline: generatedIdentity.strapline,
  description: generatedIdentity.description,
  repoUrl: generatedIdentity.repoUrl,
  accentColor: "#b7410e",
  accentColorDark: "#f28c52",
  footerSections: [
    {
      title: generatedIdentity.name,
      text: generatedIdentity.footerText
    },
    {
      title: "Distribution",
      text: generatedIdentity.distributionText
    },
    {
      title: "Repository",
      linkPrefix: "Source: ",
      linkHref: generatedIdentity.repoUrl,
      linkLabel: generatedIdentity.repoUrl.replace("https://", "")
    }
  ]
} as const;

export const docCategories = ["Start", "Development", "Distribution", "Reference"] as const;

export const primaryNav = [
  { href: "/docs", label: "Docs" },
  { href: siteConfig.repoUrl, label: "GitHub", external: true }
];

import { redirect } from "next/navigation";

// The cohort overview is the landing page; the patients list lives at /patients.
export default function Home() {
  redirect("/cohort");
}

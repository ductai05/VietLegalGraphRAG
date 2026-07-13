import { useEffect } from "react";
import Header from "../components/Header.jsx";
import Footer from "../components/Footer.jsx";
import HelpBeacon from "../components/HelpBeacon.jsx";
import Hero from "../components/landing/Hero.jsx";
import Platform from "../components/landing/Platform.jsx";
import Engine from "../components/landing/Engine.jsx";
import Workflow from "../components/landing/Workflow.jsx";
import Trust from "../components/landing/Trust.jsx";

export default function Landing() {
  // `landing-body` drives the page background treatment in styles.css.
  useEffect(() => {
    document.body.classList.add("landing-body");
    return () => document.body.classList.remove("landing-body");
  }, []);

  return (
    <>
      <Header />
      <main>
        <Hero />
        <Platform />
        <Engine />
        <Workflow />
        <Trust />
      </main>
      <Footer />
      <HelpBeacon />
    </>
  );
}

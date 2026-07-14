import { useReveal } from "../hooks/useReveal.js";

// Wrapper reproducing the `.reveal` -> `.is-visible` scroll animation.
// `delay` maps to the `.delay-1` / `.delay-2` stagger classes.
export default function Reveal({
  as: Tag = "div",
  className = "",
  delay = 0,
  children,
  ...rest
}) {
  const [ref, visible] = useReveal();
  const classes = [
    "reveal",
    delay ? `delay-${delay}` : "",
    visible ? "is-visible" : "",
    className
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Tag ref={ref} className={classes} {...rest}>
      {children}
    </Tag>
  );
}

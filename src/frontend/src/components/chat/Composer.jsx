import { useState } from "react";

export default function Composer({ onSend }) {
  const [value, setValue] = useState("");

  const handleSubmit = (event) => {
    event.preventDefault();
    onSend(value);
    setValue("");
  };

  return (
    <form className="composer" id="chat-form" onSubmit={handleSubmit}>
      <label className="sr-only" htmlFor="chat-input">Message Aurora</label>
      <input
        id="chat-input"
        name="message"
        type="text"
        autoComplete="off"
        placeholder="Message Aurora"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <button className="button button-brand" type="submit">Send ►</button>
    </form>
  );
}

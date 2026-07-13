import { useRef } from "react";

export default function OcrForm({ onSubmit }) {
  const fileRef = useRef(null);

  const handleSubmit = (event) => {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      return;
    }
    onSubmit(file).finally(() => {
      if (fileRef.current) {
        fileRef.current.value = "";
      }
    });
  };

  return (
    <form className="ocr-form" id="ocr-form" onSubmit={handleSubmit}>
      <label htmlFor="ocr-file">OCR file</label>
      <input
        id="ocr-file"
        name="file"
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif,application/pdf"
        ref={fileRef}
      />
      <button className="button button-secondary button-small" type="submit">
        Extract Text
      </button>
    </form>
  );
}

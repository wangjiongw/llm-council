import { useRef } from 'react';

export default function UploadButton({ onUpload, disabled }) {
  const fileInputRef = useRef(null);

  const handleClick = () => {
    fileInputRef.current.click();
  };

  const handleChange = async (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      await onUpload(files);
      // Reset input to allow selecting the same file again
      e.target.value = '';
    }
  };

  return (
    <>
      <button
        className="upload-button"
        onClick={handleClick}
        disabled={disabled}
        type="button"
      >
        <span>📎</span>
        <span>Upload</span>
      </button>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".txt,.md,.markdown,.json,.csv,.tsv,.xml,.yaml,.yml,.log,text/plain,text/markdown,application/json,application/pdf,image/*"
        onChange={handleChange}
        style={{ display: 'none' }}
        disabled={disabled}
      />
    </>
  );
}

import { formatFileSize } from '../utils/fileUtils';

export default function FileBubble({ file, onDelete, disabled }) {
  const isRestoredMetadata = !file.rawFile;

  return (
    <div className={`file-bubble ${disabled ? 'disabled' : ''} ${isRestoredMetadata ? 'restored' : ''}`.trim()}>
      {/* Thumbnail or icon */}
      {file.thumbnail ? (
        <img src={file.thumbnail} className="file-bubble-image" alt="" />
      ) : (
        <span className="file-bubble-icon">
          {file.category === 'image' ? '📸' : '📄'}
        </span>
      )}

      {/* File info */}
      <div className="file-bubble-info">
        <div className="file-bubble-name" title={file.name}>
          {file.name}
        </div>
        <div className="file-bubble-size">
          {isRestoredMetadata ? 'Reattach to send' : formatFileSize(file.size)}
        </div>
      </div>

      {/* Delete button */}
      {!disabled && (
        <button
          className="file-bubble-delete"
          onClick={() => onDelete(file.id)}
          aria-label="Remove file"
          type="button"
        >
          ✕
        </button>
      )}
    </div>
  );
}

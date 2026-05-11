import { useCallback } from 'react';
import FileBubble from './FileBubble';

export default function FileQueue({ files, onFilesChange, onDragOver, onDrop, disabled, onDeleteFile }) {
  const handleDelete = useCallback((fileId) => {
    // Filter out the deleted file
    const updatedFiles = files.filter(f => f.id !== fileId);

    // Update local state
    onFilesChange(updatedFiles);

    // Call backend sync callback if provided
    if (onDeleteFile) {
      onDeleteFile(fileId);
    }
  }, [files, onFilesChange, onDeleteFile]);

  if (files.length === 0) {
    return (
      <div
        className={`file-queue file-queue-empty ${disabled ? 'disabled' : ''}`}
        onDragOver={onDragOver}
        onDrop={onDrop}
      >
        <span className="file-queue-hint">拖拽文件到此处上传</span>
      </div>
    );
  }

  return (
    <div
      className={`file-queue ${disabled ? 'disabled' : ''}`}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <div className="file-bubbles">
        {files.map(file => (
          <FileBubble
            key={file.id}
            file={file}
            onDelete={handleDelete}
            disabled={disabled}
          />
        ))}
      </div>
    </div>
  );
}

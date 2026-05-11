/**
 * File utility functions
 */

/**
 * Format file size in human-readable format
 */
export function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/**
 * Generate unique ID
 */
export function generateId() {
  return `file-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Validate file
 */
export function validateFile(file, existingFiles = []) {
  const MAX_FILES = 10;
  const MAX_TEXT_SIZE = 2 * 1024 * 1024;
  const MAX_IMAGE_SIZE = 20 * 1024 * 1024;
  const MAX_PDF_SIZE = 50 * 1024 * 1024;
  const supportedTextExtensions = [
    '.txt',
    '.md',
    '.markdown',
    '.json',
    '.csv',
    '.tsv',
    '.xml',
    '.yaml',
    '.yml',
    '.log',
  ];
  const supportedTextTypes = [
    'text/plain',
    'text/markdown',
    'text/x-markdown',
    'application/markdown',
    'application/x-markdown',
    'application/json',
    'text/csv',
    'text/tab-separated-values',
    'application/xml',
    'text/xml',
    'application/x-yaml',
    'text/yaml',
  ];
  const fileName = file.name.toLowerCase();
  const isTextFile = supportedTextTypes.includes(file.type) ||
    supportedTextExtensions.some(ext => fileName.endsWith(ext));

  // Check file count limit
  if (existingFiles.length >= MAX_FILES) {
    return {
      valid: false,
      error: `最多只能上传 ${MAX_FILES} 个文件`
    };
  }

  // Check file type
  if (!isTextFile && !file.type.match(/^image\//) && file.type !== 'application/pdf') {
    return {
      valid: false,
      error: `不支持的文件类型: ${file.type}`
    };
  }

  // Check file size
  let maxSize = MAX_PDF_SIZE;
  if (isTextFile) {
    maxSize = MAX_TEXT_SIZE;
  } else if (file.type.startsWith('image/')) {
    maxSize = MAX_IMAGE_SIZE;
  }

  if (file.size > maxSize) {
    const maxMB = maxSize / (1024 * 1024);
    return {
      valid: false,
      error: `文件过大: ${(file.size / (1024 * 1024)).toFixed(1)}MB (最大 ${maxMB}MB)`
    };
  }

  return { valid: true };
}

/**
 * Create thumbnail for image file
 */
export async function createThumbnail(file) {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith('image/')) {
      resolve(null); // Not an image, no thumbnail
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => resolve(e.target.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

/**
 * Process uploaded files
 */
export async function processUploadedFiles(newFiles, existingFiles = []) {
  const MAX_FILES = 10;

  // Check total count
  if (existingFiles.length + newFiles.length > MAX_FILES) {
    throw new Error(`最多只能上传 ${MAX_FILES} 个文件`);
  }

  const validFiles = [];
  const errors = [];

  for (const file of newFiles) {
    const validation = validateFile(file, existingFiles.concat(validFiles));

    if (validation.valid) {
      // Generate thumbnail for images
      const thumbnail = await createThumbnail(file);

      validFiles.push({
        id: generateId(),
        name: file.name,
        type: file.type,
        size: file.size,
        category: file.type.startsWith('image/') ? 'image' : 'document',
        thumbnail: thumbnail,
        rawFile: file
      });
    } else {
      errors.push(`${file.name}: ${validation.error}`);
    }
  }

  if (errors.length > 0) {
    console.warn('Some files had errors:', errors);
  }

  return validFiles;
}

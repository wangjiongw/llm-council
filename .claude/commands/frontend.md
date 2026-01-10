# Frontend Development

React + Vite frontend for LLM Council.

## Purpose

This command helps you work with the React frontend using modern tooling.

## Usage

```
/frontend
```

## What this command does

1. **Installs dependencies** with npm
2. **Runs development server** with hot reload
3. **Builds for production**
4. **Runs linter** to check code quality
5. **Provides troubleshooting** for common issues

## Example Commands

### Development
```bash
cd frontend
npm run dev          # Start dev server (http://localhost:5173)
```

### Build
```bash
cd frontend
npm run build        # Build for production
npm run preview      # Preview production build
```

### Linting
```bash
cd frontend
npm run lint         # Run ESLint
```

### Dependencies
```bash
cd frontend
npm install          # Install all dependencies
npm install <pkg>    # Add a package
npm uninstall <pkg>  # Remove a package
```

## Project Structure

```
frontend/
├── src/
│   ├── main.jsx         # Entry point
│   ├── App.jsx          # Root component
│   └── ...              # Other components
├── public/              # Static assets
├── index.html           # HTML template
├── vite.config.js       # Vite configuration
├── eslint.config.js     # ESLint configuration
└── package.json         # Dependencies and scripts
```

## Tech Stack

- **React 19** - UI library
- **Vite 7** - Build tool and dev server
- **ESLint 9** - Code linting
- **react-markdown** - Markdown rendering
- **remark-gfm** - GitHub Flavored Markdown

## Common Issues

### Port already in use
```bash
# Kill process on port 5173
lsof -ti:5173 | xargs kill -9

# Or use a different port
npm run dev -- --port 3000
```

### Build errors
```bash
# Clear cache and rebuild
rm -rf node_modules dist
npm install
npm run build
```

### Module not found
```bash
# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install
```

## Integration with Backend

The frontend communicates with the FastAPI backend:

- Backend URL: `http://localhost:8001`
- API endpoints: `/api/conversations`
- CORS enabled for: `http://localhost:5173`, `http://localhost:3000`

## Best Practices

- Run dev server with `npm run dev` during development
- Run `npm run lint` before committing changes
- Build and preview before deploying
- Keep node_modules out of git (already in .gitignore)
- Use ESLint configuration for consistent code style

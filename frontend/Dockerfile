# ClauseIQ Frontend Dockerfile
# Node.js 24 + Next.js 15

# ============================================
# Stage 1: Dependencies
# ============================================
FROM node:24-alpine AS deps

WORKDIR /app

# Install dependencies for node-gyp (if needed)
RUN apk add --no-cache libc6-compat

# Copy shared types package
COPY shared ./shared

# Build shared types
WORKDIR /app/shared
RUN npm install && npm run build

# Switch to frontend
WORKDIR /app/frontend

# Copy package files
COPY frontend/package.json frontend/package-lock.json ./

# Modify package.json to use correct shared path
RUN sed -i 's|"file:../shared"|"file:/app/shared"|g' package.json

# Install dependencies
RUN npm ci

# ============================================
# Stage 2: Builder
# ============================================
FROM node:24-alpine AS builder

WORKDIR /app

# Copy shared types from deps stage
COPY --from=deps /app/shared ./shared

# Copy node_modules from deps stage
COPY --from=deps /app/frontend/node_modules ./frontend/node_modules

# Copy frontend source
COPY frontend ./frontend

# Set working directory for build
WORKDIR /app/frontend

# Modify package.json for correct path
RUN sed -i 's|"file:../shared"|"file:/app/shared"|g' package.json

# Set Next.js telemetry off
ENV NEXT_TELEMETRY_DISABLED=1

# Build the application
RUN npm run build

# ============================================
# Stage 3: Production Runner
# ============================================
FROM node:24-alpine AS runner

WORKDIR /app

# Set production environment
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy shared types (needed at runtime)
COPY --from=builder /app/shared ./shared

# Copy built assets
COPY --from=builder /app/frontend/public ./frontend/public
COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/standalone ./frontend
COPY --from=builder --chown=nextjs:nodejs /app/frontend/.next/static ./frontend/.next/static

# Set user
USER nextjs

# Expose port
EXPOSE 3000

# Set working directory
WORKDIR /app/frontend

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000 || exit 1

# Run the application
CMD ["node", "server.js"]

# ==============================================================================
# NETRA 5.0 / CyberDrishti AI — Frontend Production Multi-Stage Dockerfile
# ==============================================================================

# Stage 1: Build Vite / React SPA Bundle
FROM node:20-alpine AS builder

WORKDIR /app

# Cache dependencies layer
COPY package.json package-lock.json ./
RUN npm ci

# Copy application source
COPY . .

# Build production distribution
RUN npm run build

# Stage 2: Production Nginx Server
FROM nginx:alpine

# Remove default nginx assets
RUN rm -rf /usr/share/nginx/html/*

# Copy built distribution from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom reverse proxy configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]

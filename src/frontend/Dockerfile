# Stage 1 — build the React (Vite) app
FROM node:20-alpine AS build
WORKDIR /app
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY src/frontend/ ./
RUN npm run build

# Stage 2 — serve the static build with nginx (keeps the /api proxy)
FROM nginx:1.27-alpine
COPY src/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

FROM nginx:1.27-alpine

COPY src/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY src/frontend/ /usr/share/nginx/html/

EXPOSE 80

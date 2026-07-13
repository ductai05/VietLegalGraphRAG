FROM nginx:1.27-alpine

COPY src/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY src/frontend/*.html /usr/share/nginx/html/
COPY src/frontend/*.css /usr/share/nginx/html/
COPY src/frontend/*.js /usr/share/nginx/html/
COPY src/frontend/*.svg /usr/share/nginx/html/

EXPOSE 80

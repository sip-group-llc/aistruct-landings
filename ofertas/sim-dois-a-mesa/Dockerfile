FROM nginx:alpine
COPY . /usr/share/nginx/html
RUN rm -f /usr/share/nginx/html/Dockerfile
RUN sed -i 's|server_tokens on|server_tokens off|' /etc/nginx/nginx.conf || true

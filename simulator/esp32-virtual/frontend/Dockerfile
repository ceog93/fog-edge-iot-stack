FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html style.css script.js monitoring-data.js charts.js /usr/share/nginx/html/
COPY vendor/ /usr/share/nginx/html/vendor/
EXPOSE 80

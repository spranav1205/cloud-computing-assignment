FROM node:22-alpine
ENV NODE_ENV=production HOST=0.0.0.0 PORT=4173
WORKDIR /app
COPY --chown=node:node server.js index.html app.js styles.css ./
USER node
EXPOSE 4173
CMD ["node", "server.js"]

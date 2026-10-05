# ---------------------------------------------------------------------------
# Frontend React/Vite servi en statique par nginx (build multi-stage).
# Contexte de build : frontend/
# ---------------------------------------------------------------------------

# --- Étape 1 : build des assets ---
FROM node:20-alpine AS build

WORKDIR /app

# npm ci : installation reproductible à partir du lockfile.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_API_URL est une variable de BUILD : Vite l'inline dans le bundle.
# C'est le NAVIGATEUR qui appelle l'API, pas nginx — on vise donc le port
# publié sur l'hôte. Pas de reverse-proxy nginx vers l'API : un proxy
# bufferiserait la réponse et casserait le streaming token par token.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# --- Étape 2 : service des fichiers statiques ---
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

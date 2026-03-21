"use strict";

/**
 * Lambda@Edge (Viewer Request) — Cognito JWT verification.
 *
 * Config is loaded from SSM Parameter Store (us-east-1) on cold start, then cached.
 *
 * Flow:
 *   1. Check for `id_token` cookie
 *   2. If missing/expired -> redirect to Cognito Hosted UI login
 *   3. If valid -> pass through to origin
 *   4. /auth/callback, /health, /static -> always pass through
 */

const crypto = require("crypto");
const https = require("https");

// Cached config and JWKS keys (persist across Lambda invocations)
let cachedConfig = null;
let cachedKeys = null;

// --------------- HTTP helper ---------------
function httpsGet(url) {
  return new Promise(function (resolve, reject) {
    https.get(url, function (res) {
      var body = "";
      res.on("data", function (chunk) { body += chunk; });
      res.on("end", function () { resolve(JSON.parse(body)); });
    }).on("error", reject);
  });
}

// --------------- SSM config loader ---------------
function loadConfigFromSSM() {
  if (cachedConfig) return Promise.resolve(cachedConfig);

  // Always read from us-east-1 where the SSM parameter is stored.
  // Lambda@Edge AWS_REGION varies by edge location — do not rely on it.
  var region = "us-east-1";
  var paramName = "/deep-insight/auth-config";

  // Use AWS SDK v3 (available in Node.js 20.x Lambda runtime)
  var SSMClient = require("@aws-sdk/client-ssm").SSMClient;
  var GetParameterCommand = require("@aws-sdk/client-ssm").GetParameterCommand;

  var client = new SSMClient({ region: region });
  var command = new GetParameterCommand({ Name: paramName });

  return client.send(command).then(function (result) {
    cachedConfig = JSON.parse(result.Parameter.Value);
    return cachedConfig;
  });
}

// --------------- JWT helpers ---------------
function base64UrlDecode(str) {
  var padded = str + "=".repeat((4 - (str.length % 4)) % 4);
  return Buffer.from(padded.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

function decodeJwtPart(token, index) {
  var parts = token.split(".");
  return JSON.parse(base64UrlDecode(parts[index]).toString("utf8"));
}

function fetchJWKS(issuer) {
  if (cachedKeys) return Promise.resolve(cachedKeys);

  var url = issuer + "/.well-known/jwks.json";
  return httpsGet(url).then(function (data) {
    cachedKeys = {};
    data.keys.forEach(function (key) {
      cachedKeys[key.kid] = key;
    });
    return cachedKeys;
  });
}

function verifyJwt(token, config) {
  var header = decodeJwtPart(token, 0);
  var payload = decodeJwtPart(token, 1);
  var issuer = "https://cognito-idp." + config.region + ".amazonaws.com/" + config.userPoolId;

  // Check expiration
  if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
    return Promise.reject(new Error("Token expired"));
  }

  // Check issuer
  if (payload.iss !== issuer) {
    return Promise.reject(new Error("Invalid issuer"));
  }

  // Verify signature
  return fetchJWKS(issuer).then(function (keys) {
    var jwk = keys[header.kid];
    if (!jwk) throw new Error("Unknown key ID");

    var publicKey = crypto.createPublicKey({ key: jwk, format: "jwk" });
    var parts = token.split(".");
    var data = Buffer.from(parts[0] + "." + parts[1]);
    var signature = base64UrlDecode(parts[2]);

    var verifier = crypto.createVerify("RSA-SHA256");
    verifier.update(data);
    if (!verifier.verify(publicKey, signature)) {
      throw new Error("Invalid signature");
    }
    return payload;
  });
}

// --------------- Cookie helper ---------------
function getCookie(headers, name) {
  var cookieHeader = headers.cookie;
  if (!cookieHeader) return null;
  for (var i = 0; i < cookieHeader.length; i++) {
    var cookies = cookieHeader[i].value.split(";");
    for (var j = 0; j < cookies.length; j++) {
      var parts = cookies[j].trim().split("=");
      if (parts[0] === name) return parts.slice(1).join("=");
    }
  }
  return null;
}

// --------------- Handler ---------------
exports.handler = function (event, context, callback) {
  var request = event.Records[0].cf.request;
  var uri = request.uri;

  // Always pass through: health check, auth callback, static assets
  if (uri === "/health" || uri.indexOf("/auth/") === 0 || uri.indexOf("/static/") === 0) {
    return callback(null, request);
  }

  // Load config then verify token
  loadConfigFromSSM()
    .then(function (config) {
      var token = getCookie(request.headers, "id_token");
      if (!token) {
        return callback(null, buildRedirect(config));
      }

      return verifyJwt(token, config)
        .then(function () {
          callback(null, request);
        })
        .catch(function (err) {
          console.log("JWT verification failed:", err.message);
          callback(null, buildRedirect(config));
        });
    })
    .catch(function (err) {
      console.log("Config load failed:", err.message);
      // If config fails, pass through (ALB can still verify via origin header)
      callback(null, request);
    });
};

function buildRedirect(config) {
  var callbackUrl = encodeURIComponent(config.callbackUrl);
  var loginUrl = config.cognitoDomain + "/login?client_id=" + config.clientId +
    "&response_type=code&scope=openid+email+profile&redirect_uri=" + callbackUrl;
  return {
    status: "302",
    statusDescription: "Found",
    headers: {
      location: [{ key: "Location", value: loginUrl }],
      "cache-control": [{ key: "Cache-Control", value: "no-cache" }],
    },
  };
}

import React from 'react';
import { Link } from 'react-router-dom';

function CodeBlock({ code }) {
  const [copied, setCopied] = React.useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="dockerfile-code-block">
      <button className="copy-btn" onClick={copy}>{copied ? '✓ Copied' : 'Copy'}</button>
      <pre>{code}</pre>
    </div>
  );
}

const EXAMPLES = [
  {
    icon: '☕', title: 'Java (Spring Boot)',
    note: 'Build your jar first (mvn package or gradle build), then package it into a minimal JRE image.',
    code: `FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]`,
  },
  {
    icon: '🔷', title: '.NET',
    note: 'Publish your app (dotnet publish) so the DLL and dependencies are in the project root.',
    code: `FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY . .
EXPOSE 8080
CMD ["dotnet", "YourApp.dll"]`,
  },
  {
    icon: '🐹', title: 'Go',
    note: 'A two-stage build keeps the final image small — only the compiled binary ships.',
    code: `FROM golang:1.22-alpine AS build
WORKDIR /app
COPY . .
RUN go build -o server .

FROM alpine
COPY --from=build /app/server /server
EXPOSE 8080
CMD ["/server"]`,
  },
  {
    icon: '💎', title: 'Ruby (Rails)',
    note: 'Bundler installs gems at build time; Rails must bind to 0.0.0.0, not localhost.',
    code: `FROM ruby:3.3-slim
WORKDIR /app
COPY . .
RUN bundle install
EXPOSE 3000
CMD ["rails", "server", "-b", "0.0.0.0"]`,
  },
  {
    icon: '🦀', title: 'Rust',
    note: 'Like Go, a two-stage build avoids shipping the entire Rust toolchain.',
    code: `FROM rust:1.75 AS build
WORKDIR /app
COPY . .
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=build /app/target/release/app /app
EXPOSE 8080
CMD ["/app"]`,
  },
];

export default function DockerfileHelpPage() {
  return (
    <div className="page-dockerfile-help">
      <h1>Writing a Dockerfile</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: 12 }}>
        If we couldn't detect your stack automatically, add a file named exactly{' '}
        <code>Dockerfile</code> to the root of your project's zip. A few rules apply to every
        stack on this platform:
      </p>
      <ul style={{ color: 'var(--text-secondary)', marginBottom: 32, paddingLeft: 20, lineHeight: 1.8 }}>
        <li>Include an <code>EXPOSE &lt;port&gt;</code> line — this tells us which port your app listens on.</li>
        <li>Your app must bind to <code>0.0.0.0</code>, not <code>127.0.0.1</code> or <code>localhost</code>.</li>
        <li>Containers run as a non-root user — avoid ports below 1024, and don't rely on root-only paths.</li>
        <li><code>FROM scratch</code> is not supported — use a minimal base image instead (Alpine, slim, etc.).</li>
      </ul>

      {EXAMPLES.map((ex) => (
        <div className="dockerfile-example" key={ex.title}>
          <h3>{ex.icon} {ex.title}</h3>
          <p style={{ color: 'var(--text-muted)', marginBottom: 10, fontSize: '0.87rem' }}>{ex.note}</p>
          <CodeBlock code={ex.code} />
        </div>
      ))}

      <div className="alert alert-info" style={{ marginTop: 20 }}>
        Once your Dockerfile is in place, re-upload your project zip on the{' '}
        <Link to="/upload-project">Upload page</Link> — we'll detect it and clear the way to submit.
      </div>
    </div>
  );
}

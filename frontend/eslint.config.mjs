import next from "eslint-config-next";

const config = [...next, { ignores: [".next/**", ".playwright/**", "next-env.d.ts"] }];

export default config;

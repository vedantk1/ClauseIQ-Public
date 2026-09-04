// Frontend configuration
import { getApiBaseUrl } from "@/lib/api";

interface Config {
  apiUrl: string;
  maxFileSizeMB: number;
}

const config: Config = {
  apiUrl: getApiBaseUrl(),
  maxFileSizeMB: parseInt(process.env.NEXT_PUBLIC_MAX_FILE_SIZE_MB || "10"),
};

export default config;

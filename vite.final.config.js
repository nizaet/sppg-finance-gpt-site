import deliveryConfig from "./vite.delivery.config.js";
import uiPolishPlugin from "./vite.ui.polish.plugin.js";

export default {
  ...deliveryConfig,
  plugins: [...(deliveryConfig.plugins || []), uiPolishPlugin()],
};

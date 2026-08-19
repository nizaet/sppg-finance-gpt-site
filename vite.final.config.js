import deliveryConfig from "./vite.delivery.config.js";
import uiPolishPlugin from "./vite.ui.polish.plugin.js";

const rawUiPolish = uiPolishPlugin();
const safeUiPolish = {
  ...rawUiPolish,
  name: `${rawUiPolish.name}-safe`,
  transform(code, id) {
    try {
      return rawUiPolish.transform?.call(this, code, id) ?? null;
    } catch (error) {
      console.warn(`[ui-polish] skipped for ${id}:`, error?.message || error);
      return null;
    }
  },
};

export default {
  ...deliveryConfig,
  plugins: [...(deliveryConfig.plugins || []), safeUiPolish],
};

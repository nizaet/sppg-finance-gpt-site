import flowConfig from "./vite.flowviews2.config.js";

const plugins = (flowConfig.plugins || []).map((plugin) => {
  if (plugin?.name === "sppg-flow-calendar-and-filters-v2") {
    return { ...plugin, enforce: "pre" };
  }
  return plugin;
});

export default {
  ...flowConfig,
  plugins,
};

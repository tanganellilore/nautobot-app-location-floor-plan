// Geometry translation
(typeof window !== "undefined" ? window : global).LocationFloorPlanGeometry = {
    backendToLeaflet: function(geom) {
        if (!geom) return null;
        if (geom.type === 'polygon' && geom.points) {
            return geom.points.map(pt => [pt[1], pt[0]]);
        } else if (geom.width !== undefined && geom.height !== undefined && geom.x !== undefined && geom.y !== undefined) {
            return [[geom.y, geom.x], [geom.y + geom.height, geom.x + geom.width]];
        }
        return null;
    },
    leafletToBackend: function(layer, isRack) {
        if (isRack || (layer instanceof L.Rectangle)) {
            const bounds = layer.getBounds();
            const sw = bounds.getSouthWest();
            const ne = bounds.getNorthEast();
            return {
                x: Math.round(sw.lng),
                y: Math.round(sw.lat),
                width: Math.round(ne.lng - sw.lng),
                height: Math.round(ne.lat - sw.lat)
            };
        } else if (layer instanceof L.Polygon) {
            const latlngs = layer.getLatLngs()[0];
            return {
                type: 'polygon',
                points: latlngs.map(ll => [Math.round(ll.lng), Math.round(ll.lat)])
            };
        }
        return null;
    }
};

(typeof window !== "undefined" ? window : global).LocationFloorPlan = (function() {
    let map = null;
    let config = null;
    let mapData = null; // Contains map, location_placements, rack_placements
    let originalRevision = 0;
    
    let locationLayerGroup = null;
    let rackLayerGroup = null;
    let backgroundLayer = null;
    
    
    let isEditMode = false;
    let activeDrawing = null; // 'location' or 'rack'
    let pendingPlacementData = null;
    let knownLocations = new Map();
    let knownRacks = new Map();
    let selectedLayer = null; // The selected location/rack from picker
    let bgImageLoadPromise = null;

    
    function getThemeColor() {
        if (typeof document === 'undefined' || !document.body) return '';
        try {
            const btnPrimary = document.querySelector('.btn-primary');
            if (btnPrimary) {
                const bgColor = getComputedStyle(btnPrimary).backgroundColor;
                if (bgColor && bgColor !== 'rgba(0, 0, 0, 0)' && bgColor !== 'transparent') {
                    return bgColor;
                }
            }
            const bodyStyle = getComputedStyle(document.body);
            const bsPrimary = bodyStyle.getPropertyValue('--bs-primary').trim();
            if (bsPrimary) {
                return bsPrimary;
            }
            return bodyStyle.color;
        } catch(e) {
            return '';
        }
    }

    let contextActionLayer = null;

    function updateEditLabel(layer) {
        const label = layer && layer.options.editLabel;
        if (label && layer.getBounds) {
            label.setLatLng(layer.getBounds().getCenter());
        }
    }

    function attachEditLabel(layer, name) {
        if (!map || !layer.getBounds) return;
        const label = L.tooltip({
            permanent: true,
            interactive: false,
            direction: 'center',
            className: 'lfp-edit-label'
        })
        .setLatLng(layer.getBounds().getCenter())
        .setContent(createTooltipContent(name, null))
        .addTo(map);
        const update = () => updateEditLabel(layer);
        layer.options.editLabel = label;
        layer.options.editLabelUpdater = update;
        layer.on('pm:drag pm:markerdrag pm:change pm:edit', update);
    }

    function removeEditLabel(layer) {
        if (!layer) return;
        if (layer.options.editLabelUpdater) {
            layer.off('pm:drag pm:markerdrag pm:change pm:edit', layer.options.editLabelUpdater);
        }
        if (layer.options.editLabel && map) {
            map.removeLayer(layer.options.editLabel);
        }
        delete layer.options.editLabel;
        delete layer.options.editLabelUpdater;
    }

    function closeContextAction() {
        if (contextActionLayer) {
            contextActionLayer.closeTooltip();
            contextActionLayer.unbindTooltip();
        }
        contextActionLayer = null;
    }
    
    function selectLayer(layer, evt = null) {
        if (selectedLayer && selectedLayer._path) {
            L.DomUtil.removeClass(selectedLayer._path, 'lfp-selected-layer');
            selectedLayer.off('pm:dragstart', closeContextAction);
            selectedLayer.off('pm:markerdragstart', closeContextAction);
            selectedLayer.off('pm:edit', closeContextAction);
        }
        selectedLayer = layer;
        
        closeContextAction();

        if (selectedLayer) {
            if (selectedLayer._path) L.DomUtil.addClass(selectedLayer._path, 'lfp-selected-layer');
            
            const btn = document.createElement('button');
            btn.className = 'btn btn-danger btn-sm rounded-circle d-inline-flex align-items-center justify-content-center p-2';
            btn.setAttribute('aria-label', 'Delete selected placement');
            btn.setAttribute('title', 'Delete');
            
            const icon = document.createElement('i');
            icon.className = 'mdi mdi-delete';
            btn.appendChild(icon);
            
            btn.onclick = (e) => {
                L.DomEvent.stopPropagation(e);
                deleteSelectedLayer();
            };
            btn.onmousedown = (e) => L.DomEvent.stopPropagation(e);
            
            const panel = document.createElement('div');
            panel.className = 'lfp-action-panel';
            panel.appendChild(btn);
            
            let anchorLatLng = null;
            if (selectedLayer.getBounds) {
                const bounds = selectedLayer.getBounds();
                anchorLatLng = L.latLng(bounds.getNorth(), bounds.getCenter().lng);
            }

            if (anchorLatLng && map) {
                selectedLayer.bindTooltip(panel, {
                    permanent: true,
                    interactive: true,
                    direction: 'top',
                    offset: [0, -10],
                    className: 'lfp-action-tooltip'
                }).openTooltip(anchorLatLng);
                contextActionLayer = selectedLayer;
                contextAction = selectedLayer.getTooltip();

                selectedLayer.on('pm:dragstart', closeContextAction);
                selectedLayer.on('pm:markerdragstart', closeContextAction);
                selectedLayer.on('pm:edit', closeContextAction);
            }
        }
    }

    function deleteSelectedLayer() {
        if (mapData && mapData.inherited) return;
        if (selectedLayer) {
            removeEditLabel(selectedLayer);
            locationLayerGroup.removeLayer(selectedLayer);
            rackLayerGroup.removeLayer(selectedLayer);
            if (map.hasLayer(selectedLayer)) {
                map.removeLayer(selectedLayer);
            }
            selectLayer(null);
        }
    }

    // Modals
    function showAlert(title, message) {
        return new Promise(resolve => {
            document.getElementById('lfp-alert-title').textContent = title;
            document.getElementById('lfp-alert-message').textContent = message;
            const modalEl = document.getElementById('lfp-alert-modal');
            const modal = typeof bootstrap !== 'undefined' ? bootstrap.Modal.getOrCreateInstance(modalEl) : { show: () => modalEl.dispatchEvent(new Event('shown.bs.modal')), hide: () => modalEl.dispatchEvent(new Event('hidden.bs.modal')) };
            let resolved = false;
            
            const onHidden = () => {
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
                if (!resolved) {
                    resolved = true;
                    resolve();
                }
            };
            modalEl.addEventListener('hidden.bs.modal', onHidden);
            modal.show();
        });
    }

    function showConfirm(title, message) {
        return new Promise(resolve => {
            document.getElementById('lfp-confirm-title').textContent = title;
            document.getElementById('lfp-confirm-message').textContent = message;
            const modalEl = document.getElementById('lfp-confirm-modal');
            const modal = typeof bootstrap !== 'undefined' ? bootstrap.Modal.getOrCreateInstance(modalEl) : { show: () => modalEl.dispatchEvent(new Event('shown.bs.modal')), hide: () => modalEl.dispatchEvent(new Event('hidden.bs.modal')) };
            let resolved = false;
            
            const yesBtn = document.getElementById('lfp-confirm-yes');
            
            const cleanup = () => {
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
                yesBtn.onclick = null;
            };
            
            const onHidden = () => {
                cleanup();
                if (!resolved) {
                    resolved = true;
                    resolve(false);
                }
            };
            
            yesBtn.onclick = () => {
                cleanup();
                if (!resolved) {
                    resolved = true;
                    resolve(true);
                    modal.hide();
                }
            };
            
            modalEl.addEventListener('hidden.bs.modal', onHidden);
            modal.show();
        });
    }

    let select2Initialized = false;
    function showPicker(title, items, labelText) {
        return new Promise(resolve => {
            document.getElementById('lfp-picker-title').textContent = title;
            const labelEl = document.getElementById('lfp-picker-label');
            if (labelEl) labelEl.textContent = labelText || 'Available Items';
            
            const modalEl = document.getElementById('lfp-picker-modal');
            const modal = typeof bootstrap !== 'undefined' ? bootstrap.Modal.getOrCreateInstance(modalEl) : { show: () => modalEl.dispatchEvent(new Event('shown.bs.modal')), hide: () => modalEl.dispatchEvent(new Event('hidden.bs.modal')) };
            const selectEl = document.getElementById('id_target');
            const placeBtn = document.getElementById('lfp-picker-place');
            let resolved = false;
            
            while (selectEl.firstChild) { selectEl.removeChild(selectEl.firstChild); }
            
            const defaultOpt = document.createElement('option');
            defaultOpt.value = "";
            defaultOpt.disabled = true;
            defaultOpt.selected = true;
            defaultOpt.textContent = "---------";
            selectEl.appendChild(defaultOpt);
            
            if (items.length === 0) {
                defaultOpt.textContent = "No available items to place.";
            } else {
                items.forEach(item => {
                    const opt = document.createElement('option');
                    opt.value = item.id;
                    opt.textContent = item.name;
                    selectEl.appendChild(opt);
                });
            }
            
            placeBtn.disabled = true;
            
            const onChange = () => {
                placeBtn.disabled = !selectEl.value;
            };
            if (typeof window.jQuery !== 'undefined') {
                window.jQuery(selectEl).on('change', onChange);
            } else {
                selectEl.addEventListener('change', onChange);
            }

            const cleanup = () => {
                if (typeof window.jQuery !== 'undefined') {
                    if (select2Initialized) {
                        try { window.jQuery(selectEl).select2('close'); } catch(e) {}
                    }
                    selectEl.value = "";
                    window.jQuery(selectEl).trigger('change');
                    window.jQuery(selectEl).off('change', onChange);
                } else {
                    selectEl.value = "";
                    selectEl.removeEventListener('change', onChange);
                }
                placeBtn.onclick = null;
                modalEl.removeEventListener('shown.bs.modal', onShown);
                modalEl.removeEventListener('hidden.bs.modal', onHidden);
            };

            const onHidden = () => {
                cleanup();
                if (!resolved) {
                    resolved = true;
                    resolve(null);
                }
            };
            
            const onShown = () => {
                if (typeof window.jQuery !== 'undefined') {
                    if (!select2Initialized) {
                        try { window.jQuery(selectEl).select2('destroy'); } catch(e) {}
                        window.jQuery(selectEl).select2({
                            theme: 'bootstrap-5',
                            dropdownParent: window.jQuery('#lfp-picker-modal'),
                            width: '100%',
                            selectionCssClass: 'select2--small',
                            allowClear: true,
                            placeholder: '---------'
                        });
                        select2Initialized = true;
                    }
                    window.jQuery(selectEl).trigger('change');
                }
            };

            placeBtn.onclick = () => { 
                const selectedId = selectEl.value;
                const selectedItem = items.find(i => String(i.id) === String(selectedId));
                cleanup(); 
                if (!resolved) {
                    resolved = true;
                    resolve(selectedItem || null); 
                    modal.hide();
                }
            };
            
            modalEl.addEventListener('shown.bs.modal', onShown);
            modalEl.addEventListener('hidden.bs.modal', onHidden);
            modal.show();
        });
    }

    function createTooltipContent(name, subtext) {
        const div = document.createElement('div');
        div.className = 'lfp-label';
        const strStrong = document.createElement('span');
        strStrong.textContent = name;
        div.appendChild(strStrong);
        if (subtext) {
            const br = document.createElement('br');
            const span = document.createElement('span');
            span.textContent = subtext;
            div.appendChild(br);
            div.appendChild(span);
        }
        return div;
    }

    // Main Init
    function init() {
        config = {
            locationId: JSON.parse(document.getElementById('lfp-location-id').textContent),
            permissions: JSON.parse(document.getElementById('lfp-permissions').textContent),
            apiResolvedUrl: JSON.parse(document.getElementById('lfp-api-resolved-url').textContent),
            apiMapListUrl: JSON.parse(document.getElementById('lfp-api-map-list-url').textContent),
            csrfToken: JSON.parse(document.getElementById('lfp-csrf-token').textContent)
        };
        config.hasEditPermission = config.permissions.addMap || config.permissions.changeMap || config.permissions.deleteMap;

        document.getElementById('btn-lfp-reload')?.addEventListener('click', loadMapData);
        
        if (config.hasEditPermission) {
            document.getElementById('btn-lfp-create-map')?.addEventListener('click', createMapFlow);

            const bgInputInit = document.getElementById('lfp-map-bg');
            if (bgInputInit) {
                bgInputInit.addEventListener('change', function(e) {
                    const file = e.target.files && e.target.files[0];
                    if (!file) {
                        bgImageLoadPromise = null;
                        return;
                    }
                    bgImageLoadPromise = new Promise((resolve) => {
                        const url = URL.createObjectURL(file);
                        const img = new Image();
                        img.onload = function() {
                            const wInput = document.getElementById("lfp-map-width");
                            const hInput = document.getElementById("lfp-map-height");
                            if (wInput && hInput) {
                                wInput.value = img.naturalWidth;
                                hInput.value = img.naturalHeight;
                            }
                            URL.revokeObjectURL(url);
                            resolve();
                        };
                        img.onerror = function() {
                            URL.revokeObjectURL(url);
                            resolve();
                        };
                        img.src = url;
                    });
                });
            }
            document.getElementById('btn-lfp-edit')?.addEventListener('click', toggleEditMode);
            document.getElementById('btn-lfp-save')?.addEventListener('click', saveMap);
            document.getElementById('btn-lfp-cancel')?.addEventListener('click', cancelEdit);
            
            // Toolbar
            document.getElementById('btn-lfp-add-loc')?.addEventListener('click', () => addPlacementFlow('location'));
            document.getElementById('btn-lfp-add-rack')?.addEventListener('click', () => addPlacementFlow('rack'));
            document.getElementById('btn-lfp-delete-map')?.addEventListener('click', deleteMapFlow);
            
            document.addEventListener('keydown', (e) => {
                if (!isEditMode || !selectedLayer) return;
                if (document.body.classList.contains('modal-open')) return;
                
                const active = document.activeElement;
                if (active) {
                    const tag = active.tagName.toUpperCase();
                    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || active.isContentEditable) return;
                }

                if (e.key === 'Delete' || e.key === 'Backspace') {
                    e.preventDefault();
                    deleteSelectedLayer();
                }
            });
            document.getElementById('btn-lfp-replace-bg')?.addEventListener('click', () => document.getElementById('lfp-replace-bg')?.click());
            document.getElementById('lfp-replace-bg')?.addEventListener('change', replaceBackgroundFlow);
        }
        
        loadMapData();
    }

    function setUIState(state, errorMsg = '') {
        document.getElementById('lfp-loading').classList.add('lfp-hidden');
        document.getElementById('lfp-no-map').classList.add('lfp-hidden');
        document.getElementById('lfp-error').classList.add('lfp-hidden');
        document.getElementById('location-floor-plan-map').classList.add('lfp-hidden');
        document.getElementById('lfp-inherited-alert')?.classList.add('lfp-hidden');
        
        if (config.hasEditPermission) {
            document.getElementById('lfp-toolbar-view').classList.add('lfp-hidden');
            document.getElementById('lfp-toolbar-edit').classList.add('lfp-hidden');
        }

        if (state === 'loading') {
            document.getElementById('lfp-loading').classList.remove('lfp-hidden');
        } else if (state === 'error') {
            document.getElementById('lfp-error').classList.remove('lfp-hidden');
            document.getElementById('lfp-error-message').textContent = errorMsg;
        } else if (state === 'no-map') {
            document.getElementById('lfp-no-map').classList.remove('lfp-hidden');
        } else if (state === 'view') {
            document.getElementById('location-floor-plan-map').classList.remove('lfp-hidden');
            if (config.hasEditPermission) document.getElementById('lfp-toolbar-view').classList.remove('lfp-hidden');
        } else if (state === 'edit') {
            document.getElementById('location-floor-plan-map').classList.remove('lfp-hidden');
            if (config.hasEditPermission) document.getElementById('lfp-toolbar-edit').classList.remove('lfp-hidden');
        }
    }

    async function loadMapData() {
        setUIState('loading');
        try {
            const response = await fetch(config.apiResolvedUrl, {
                headers: { 'Accept': 'application/json', 'X-CSRFToken': config.csrfToken }
            });
            if (response.status === 404) {
                setUIState('no-map');
                return;
            }
            if (!response.ok) throw new Error("Failed to load map data");
            
            const data = await response.json();
            if (!data.map || !data.map.id) {
                setUIState('no-map');
                return;
            }
            
            mapData = {
                map: data.map,
                location_placements: data.location_placements || data.locations || [],
                rack_placements: data.rack_placements || data.racks || [],
                focus: data.focus,
                inherited: data.inherited
            };
            
                        originalRevision = mapData.map.revision || 0;
            
            mapData.location_placements.forEach(lp => {
                const id = lp.location?.id || lp.id;
                const name = lp.location?.name || lp.name || 'Location';
                if (id) knownLocations.set(id, {id, name});
            });
            mapData.rack_placements.forEach(rp => {
                const id = rp.rack?.id || rp.id;
                const name = rp.rack?.name || rp.name || 'Rack';
                if (id) knownRacks.set(id, {id, name});
            });
            
            setUIState('view');
            
            const editBtn = document.getElementById('btn-lfp-edit');
            const inheritedAlert = document.getElementById('lfp-inherited-alert');
            if (mapData.inherited) {
                if (editBtn) {
                    editBtn.disabled = true;
                    editBtn.setAttribute('aria-disabled', 'true');
                    editBtn.title = 'Inherited maps must be edited from their owning location.';
                }
                if (inheritedAlert) inheritedAlert.classList.remove('lfp-hidden');
            } else {
                if (editBtn) {
                    editBtn.disabled = false;
                    editBtn.removeAttribute('aria-disabled');
                    editBtn.removeAttribute('title');
                }
                if (inheritedAlert) inheritedAlert.classList.add('lfp-hidden');
            }
            
            renderMap();
        } catch (e) {
            console.error(e);
            setUIState('error', "Error loading map: " + e.message);
        }
    }

    function renderMap() {
        if (backgroundLayer) backgroundLayer.remove();
        if (map) map.remove();

        const logicalWidth = mapData.map.logical_width || 1000;
        const logicalHeight = mapData.map.logical_height || 1000;

        map = L.map('location-floor-plan-map', {
            crs: L.CRS.Simple,
            minZoom: -5, maxZoom: 5,
            zoomSnap: 0,
            zoomDelta: 0.5,
            zoomControl: true, scrollWheelZoom: true
        });

        map.createPane('backgroundPane');
        map.getPane('backgroundPane').style.zIndex = 200;
        map.getPane('backgroundPane').style.pointerEvents = 'none';
        
        map.createPane('locationPane');
        map.getPane('locationPane').style.zIndex = 300;
        
        map.createPane('rackPane');
        map.getPane('rackPane').style.zIndex = 400;

        const bounds = [[0, 0], [logicalHeight, logicalWidth]];
        backgroundLayer = null;
        if (mapData.map.background_url) {
            backgroundLayer = L.imageOverlay(mapData.map.background_url, bounds, { pane: 'backgroundPane' }).addTo(map);
        }

        locationLayerGroup = L.layerGroup().addTo(map);
        rackLayerGroup = L.layerGroup().addTo(map);
        drawObjects();

        // inherited mode focus
        if (mapData.inherited && mapData.focus && mapData.focus.geometry) {
            const focusBounds = (typeof window !== "undefined" ? window : global).LocationFloorPlanGeometry.backendToLeaflet(mapData.focus.geometry);
            if (focusBounds) map.fitBounds(focusBounds);
        } else {
            map.fitBounds(bounds);
        }
        
        // Handle Geoman creates
                map.on('click', () => {
            if (isEditMode) selectLayer(null);
        });

        map.on('pm:create', (e) => {
            const layer = e.layer;
            layer.options.bubblingMouseEvents = false;
            if (activeDrawing && pendingPlacementData) {
                if (activeDrawing === 'location') {
                    layer.options.placementId = null; // New placement
                    layer.options.targetId = pendingPlacementData.id;
                    layer.options.targetName = pendingPlacementData.name;
                    layer.options.pane = 'locationPane';
                    layer.options.className = 'lfp-location-poly';
                    // Bugfix: adding to group right after create requires a timeout or removing from map first
                    map.removeLayer(layer);
                    locationLayerGroup.addLayer(layer);
                    attachEditLabel(layer, pendingPlacementData.name);
                    layer.on('click', (evt) => {
                        if (isEditMode) {
                            if (evt.originalEvent) L.DomEvent.stopPropagation(evt.originalEvent);
                            selectLayer(layer, evt);
                        }
                    });
                                                        } else if (activeDrawing === 'rack') {
                    layer.options.placementId = null;
                    layer.options.targetId = pendingPlacementData.id;
                    layer.options.targetName = pendingPlacementData.name;
                    layer.options.pane = 'rackPane';
                    layer.options.className = 'rack-placement rack-usage-empty';
                    map.removeLayer(layer);
                    rackLayerGroup.addLayer(layer);
                    attachEditLabel(layer, pendingPlacementData.name);
                    layer.on('click', (evt) => {
                        if (isEditMode) {
                            if (evt.originalEvent) L.DomEvent.stopPropagation(evt.originalEvent);
                            selectLayer(layer, evt);
                        }
                    });
                                                        }
            }
            // Reset to select mode
            setDrawMode(null);
        });
    }

    function drawObjects() {
        locationLayerGroup.clearLayers();
        rackLayerGroup.clearLayers();
        
        mapData.location_placements.forEach(lp => {
            const geom = (typeof window !== "undefined" ? window : global).LocationFloorPlanGeometry.backendToLeaflet(lp.geometry);
            if (!geom) return;
            const targetId = lp.location?.id || lp.id;
            const targetName = lp.location?.name || lp.name || 'Location';
            
            const isRect = lp.geometry.width !== undefined;
            const poly = isRect ? L.rectangle(geom, { pane: 'locationPane', className: 'lfp-location-poly', pmIgnore: false, bubblingMouseEvents: false }) : 
                                  L.polygon(geom, { pane: 'locationPane', className: 'lfp-location-poly', pmIgnore: false, bubblingMouseEvents: false });
            
            poly.options.placementId = lp.id;
            poly.options.targetId = targetId;
            poly.options.targetName = targetName;
            
            if (isEditMode) {
                attachEditLabel(poly, targetName);
            } else {
                poly.bindTooltip(createTooltipContent(targetName, null), {permanent: false, direction: 'top'});
            }
            
            if (!isEditMode && lp.detail_url) {
                poly.on('click', () => { window.location.href = lp.detail_url; });
                poly.options.pmIgnore = true;
            } else if (isEditMode) {
                poly.on('click', (evt) => {
                    if (evt.originalEvent) L.DomEvent.stopPropagation(evt.originalEvent);
                    selectLayer(poly, evt);
                });
                                            }
            poly.addTo(locationLayerGroup);
        });

        mapData.rack_placements.forEach(rp => {
            const geom = (typeof window !== "undefined" ? window : global).LocationFloorPlanGeometry.backendToLeaflet(rp.geometry || rp);
            if (!geom) return;
            const targetId = rp.rack?.id || rp.id;
            const targetName = rp.rack?.name || rp.name || 'Rack';
            
            // Rely on backend percentage and usage level classes
            const usageClass = rp.usage_level ? `rack-usage-${rp.usage_level}` : 'rack-usage-empty';
            const usageText = rp.usage_percentage !== undefined ? `${rp.usage_percentage}%` : '0%';
            
            const rect = L.rectangle(geom, { pane: 'rackPane', className: `rack-placement ${usageClass}`, pmIgnore: false, bubblingMouseEvents: false });
            rect.options.placementId = rp.id;
            rect.options.targetId = targetId;
            rect.options.targetName = targetName;
            
            let subtextParts = [];
            if (rp.used_ru !== undefined && rp.total_ru !== undefined) {
                subtextParts.push(`${rp.used_ru} / ${rp.total_ru} RU`);
            }
            if (rp.usage_percentage !== undefined) {
                subtextParts.push(`${rp.usage_percentage}%`);
            }
            if (rp.usage_level !== undefined) {
                subtextParts.push(`${rp.usage_level} utilization`);
            }
            
            let subtext = '';
            if (subtextParts.length > 0) {
                subtext = subtextParts.join(' · ');
            } else {
                subtext = rp.label || rp.aria_label || '';
                const prefix = `${targetName}: `;
                if (subtext.startsWith(prefix)) {
                    subtext = subtext.substring(prefix.length);
                }
                if (!subtext) {
                    const uLvl = rp.usage_level || 'empty';
                    subtext = `Usage: ${usageText} (${uLvl})`;
                }
            }
            if (isEditMode) {
                attachEditLabel(rect, targetName);
            } else {
                rect.bindTooltip(createTooltipContent(targetName, subtext), {permanent: false, direction: 'top'});
            }
            rect.options.ariaLabel = rp.aria_label || rp.label || `${targetName} ${usageText}`;
            
            if (!isEditMode && rp.detail_url) {
                rect.on('click', () => { window.location.href = rp.detail_url; });
                rect.options.pmIgnore = true;
            } else if (isEditMode) {
                rect.on('click', (evt) => {
                    if (evt.originalEvent) L.DomEvent.stopPropagation(evt.originalEvent);
                    selectLayer(rect, evt);
                });
                                            }
            rect.addTo(rackLayerGroup);
        });
    }

    function toggleEditMode() {
        if (mapData && mapData.inherited) return;
        if (!map) return;
        isEditMode = true;
        setUIState('edit');
        
        map.pm.addControls({
            position: 'topleft',
            drawMarker: false, drawCircleMarker: false, drawPolyline: false, drawRectangle: false,
            drawPolygon: false, drawText: false, drawCircle: false,
            editMode: true, dragMode: true, cutPolygon: false, removalMode: false
        });
        const c = getThemeColor();
        map.pm.setGlobalOptions({
            templineStyle: { color: c, weight: 3, dashArray: "5,5" },
            hintlineStyle: { color: c, weight: 3, dashArray: "5,5" },
            pathOptions: { color: c, weight: 3, fillColor: c, fillOpacity: 0.1 }
        });

        // Hide Geoman default toolbar to force use of our buttons
        const geomanToolbar = document.querySelector('.leaflet-pm-toolbar');
        if (geomanToolbar) geomanToolbar.style.display = 'none';

        drawObjects();
        setDrawMode(null);
        selectLayer(null);
    }

    function cancelEdit() {
        isEditMode = false;
        if (map) {
            map.pm.disableDraw();
            map.pm.disableGlobalEditMode();
            
            const geomanToolbar = document.querySelector('.leaflet-pm-toolbar');
            if (geomanToolbar) geomanToolbar.style.display = '';
        }
        selectLayer(null);
        setUIState('view');
        renderMap(); // Re-render from last saved mapData
    }

    function setDrawMode(mode) {
        if (!map) return;
        activeDrawing = mode;
        
        // Reset all buttons
        ['btn-lfp-select', 'btn-lfp-add-loc', 'btn-lfp-add-rack', 'btn-lfp-delete'].forEach(id => {
            document.getElementById(id)?.classList.remove('active');
        });
        
        map.pm.disableDraw();
        
        map.pm.enableGlobalEditMode(); // Always on in edit mode
        
        if (!mode) {
            document.getElementById('btn-lfp-select')?.classList.add('active');
        } else if (mode === 'location') {
            document.getElementById('btn-lfp-add-loc')?.classList.add('active');
            const c = getThemeColor();
            map.pm.enableDraw('Polygon', { snappable: true, snapDistance: 20, templineStyle: { color: c, weight: 3, dashArray: '5,5' }, hintlineStyle: { color: c, weight: 3, dashArray: '5,5' }, pathOptions: { color: c, weight: 3, dashArray: '5,5', fillColor: c, fillOpacity: 0.1, bubblingMouseEvents: false } });
        } else if (mode === 'rack') {
            document.getElementById('btn-lfp-add-rack')?.classList.add('active');
            const c = getThemeColor();
            map.pm.enableDraw('Rectangle', { snappable: true, snapDistance: 20, templineStyle: { color: c, weight: 3 }, hintlineStyle: { color: c, weight: 3 }, pathOptions: { color: c, weight: 3, fillColor: c, fillOpacity: 0.1, bubblingMouseEvents: false } });
        }
    }

    async function fetchApi(url, method = 'GET', body = null) {
        const headers = { 'Accept': 'application/json', 'X-CSRFToken': config.csrfToken };
        if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
        
        const options = { method, headers };
        if (body) options.body = body instanceof FormData ? body : JSON.stringify(body);
        
        const response = await fetch(url, options);
        return response;
    }

    async function addPlacementFlow(type) {
        if (mapData && mapData.inherited) return;
        const url = mapActionUrl(mapData.map.id, 'descendants');
        
        try {
            const response = await fetchApi(url);
            if (!response.ok) throw new Error("Failed to fetch available items");
            const payload = await response.json();
            const fetchedItems = (type === 'location' ? payload.locations : payload.racks).map(item => ({id: item.id, name: item.name || item.display}));
            
            const known = type === 'location' ? knownLocations : knownRacks;
            fetchedItems.forEach(item => known.set(item.id, item));
            
            const activeIds = new Set();
            const activeGroup = type === 'location' ? locationLayerGroup : rackLayerGroup;
            activeGroup.eachLayer(layer => {
                if (layer.options.targetId) activeIds.add(layer.options.targetId);
            });
            
            const items = [];
            for (const [id, item] of known.entries()) {
                if (!activeIds.has(id)) items.push(item);
            }
            
            const labelText = `Available ${type === 'location' ? 'Locations' : 'Racks'}`;
            const selected = await showPicker(`Select ${type === 'location' ? 'Location' : 'Rack'} to place`, items, labelText);
            if (selected) {
                pendingPlacementData = selected;
                setDrawMode(type);
            } else {
                setDrawMode(null);
            }
        } catch(e) {
            showAlert("Error", "Could not fetch available items: " + e.message);
            setDrawMode(null);
        }
    }

    async function saveMap() {
        if (mapData && mapData.inherited) return;
        const url = mapActionUrl(mapData.map.id, 'snapshot');
        
        const newLocations = [];
        locationLayerGroup.eachLayer(layer => {
            const geom = (typeof window !== "undefined" ? window : global).LocationFloorPlanGeometry.leafletToBackend(layer, false);
            if (geom) {
                const placement = { location: layer.options.targetId, geometry: geom };
                if (layer.options.placementId) placement.id = layer.options.placementId;
                newLocations.push(placement);
            }
        });
        
        const newRacks = [];
        rackLayerGroup.eachLayer(layer => {
            const geom = (typeof window !== "undefined" ? window : global).LocationFloorPlanGeometry.leafletToBackend(layer, true);
            if (geom) {
                const placement = { rack: layer.options.targetId, x: geom.x, y: geom.y, width: geom.width, height: geom.height };
                newRacks.push(placement);
            }
        });

        const snapshot = {
            expected_revision: originalRevision,
            location_placements: newLocations,
            rack_placements: newRacks
        };

        try {
            const response = await fetch(url, {
                method: 'PUT',
                headers: { 
                    'Content-Type': 'application/json', 
                    'Accept': 'application/json', 
                    'X-CSRFToken': config.csrfToken,
                    'If-Match': originalRevision.toString()
                },
                body: JSON.stringify(snapshot)
            });
            
            if (response.status === 409) {
                await showAlert("Conflict", "The map has been modified by someone else. Please reload.");
                return;
            }
            if (!response.ok) throw new Error(`Save failed (HTTP ${response.status})`);
            
            isEditMode = false;
            await loadMapData();
        } catch (e) {
            showAlert("Error", "Error saving: " + e.message);
        }
    }

    async function createMapFlow() {
        if (bgImageLoadPromise) {
            await bgImageLoadPromise;
        }
        const width = document.getElementById("lfp-map-width").value;
        const height = document.getElementById("lfp-map-height").value;
        const bgInput = document.getElementById("lfp-map-bg");
        
        if (width && height) {
            try {
                // Create map
                const createResp = await fetch(config.apiMapListUrl, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': config.csrfToken, 'If-None-Match': '*'},
                    body: JSON.stringify({
                    location: config.locationId,
                    logical_width: parseInt(width),
                    logical_height: parseInt(height),
                    expected_revision: 0
                    })
                });
                
                if (!createResp.ok) throw new Error("Failed to create map.");
                const newMap = await createResp.json();
                
                // Upload background
                if (bgInput.files && bgInput.files[0]) {
                    const formData = new FormData();
                    formData.append('background', bgInput.files[0]);
                    formData.append('expected_revision', newMap.revision || 1);
                    await fetch(mapActionUrl(newMap.id, 'background'), {method: 'PUT', headers: {'Accept': 'application/json', 'X-CSRFToken': config.csrfToken, 'If-Match': String(newMap.revision || 1)}, body: formData});
                }
                
                await loadMapData();
            } catch(e) {
                showAlert("Error", e.message);
            }
        }
    }
    
    async function deleteMapFlow() {
        if (mapData && mapData.inherited) return;
        if (!mapData || !mapData.map) return;
        // Simple DOM confirm using standard dialog logic or just alert, but we must use DOM.
        // Alert modal is 1 button, for confirm we need 2. We can reuse picker with yes/no.
        const confirmed = await showConfirm("Confirm Delete Map", "Are you sure you want to delete this map? This action cannot be undone.");
        if (confirmed) {
            try {
                const response = await fetch(mapDetailUrl(mapData.map.id), {method: 'DELETE', headers: {'Accept': 'application/json', 'X-CSRFToken': config.csrfToken, 'If-Match': String(originalRevision)}});
                if (!response.ok) throw new Error("Failed to delete map");
                
                isEditMode = false;
                await loadMapData();
            } catch(e) {
                showAlert("Error", "Delete failed: " + e.message);
            }
        }
    }

    function mapDetailUrl(mapId) {
        return `${config.apiMapListUrl}${encodeURIComponent(mapId)}/`;
    }

    function mapActionUrl(mapId, action) {
        return `${mapDetailUrl(mapId)}${action}/`;
    }

    async function replaceBackgroundFlow(event) {
        if (mapData && mapData.inherited) return;
        const file = event.target.files && event.target.files[0];
        if (!file || !mapData || !mapData.map) return;
        const formData = new FormData();
        formData.append('background', file);
        formData.append('expected_revision', originalRevision);
        try {
            const response = await fetch(mapActionUrl(mapData.map.id, 'background'), {method: 'PUT', headers: {'Accept': 'application/json', 'X-CSRFToken': config.csrfToken, 'If-Match': String(originalRevision)}, body: formData});
            if (!response.ok) throw new Error(await response.text());
            await loadMapData();
        } catch (e) {
            showAlert("Error", "Background upload failed: " + e.message);
        }
    }

    return { init: init, mapActionUrl: mapActionUrl, mapDetailUrl: mapDetailUrl };
})();

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            (typeof window !== "undefined" ? window : global).LocationFloorPlan.init();
        });
    } else {
        (typeof window !== "undefined" ? window : global).LocationFloorPlan.init();
    }
}
